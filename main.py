import logging
import time
import threading
import queue
import re
import requests
from email_client import EmailClient
from complaint_processor import ComplaintProcessor
from utils import parse_interval, load_delta_tokens, save_delta_tokens
import config
import os

# Configure logging (ONLY in main.py)
log_level = getattr(logging, config.LOG_LEVEL.upper(), logging.INFO)
logging.basicConfig(level=log_level, format='%(asctime)s - %(levelname)s - %(module)s - %(message)s')
logger = logging.getLogger(__name__)

def check_for_fp_feedback(mailbox_address: str, access_token_queue: queue.Queue, email_client: EmailClient):
    while True:
        access_token = access_token_queue.get()
        if access_token:
            try:
                graph_api_url = f"https://graph.microsoft.com/v1.0/users/{mailbox_address}/mailFolders/Inbox/messages"
                headers = {
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": "application/json"
                }
                response = requests.get(graph_api_url, headers=headers)
                response.raise_for_status()
                retrieved_emails = response.json().get("value", [])
                for message in retrieved_emails:
                    match = re.search(r"X-Complaint-Processor: Processed-v1.0; ID=(.*?);", message["body"]["content"])
                    if match:
                        email_id = match.group(1)
                        logger.info(f"False Positive detected for {mailbox_address}: Email ID: {email_id}, Subject: {message.get('subject')}, Original Message ID: {message.get('id')}")
            except requests.exceptions.RequestException as e:
                logger.exception(f"Error checking for false positives for {mailbox_address}: {e}")
            except Exception as e:
                logger.exception(f"A general error occurred in check_for_fp_feedback for {mailbox_address}: {e}")
        else:
            logger.error(f"Could not get access token for false positive check for {mailbox_address}.")
        time.sleep(parse_interval(config.SCHEDULING_INTERVALS.get("fp_feedback_loop", "5m")))
        access_token_queue.put(email_client.get_access_token())

def check_for_fn_feedback(mailbox_address: str, access_token_queue: queue.Queue, email_client: EmailClient):
    while True:
        access_token = access_token_queue.get()
        if access_token:
            try:
                graph_api_url = f"https://graph.microsoft.com/v1.0/users/{mailbox_address}/mailFolders/Inbox/messages"
                headers = {
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": "application/json"
                }
                response = requests.get(graph_api_url, headers=headers)
                response.raise_for_status()
                messages = response.json().get("value", [])

                for message in messages:
                    if message.get("toRecipients") and any(address.get("emailAddress",{}).get("address") == config.DISTRIBUTION_LIST_EMAIL for address in message.get("toRecipients", [])):
                        logger.info(f"Potential False Negative Detected for {mailbox_address}: Subject: {message.get('subject')}, From: {message.get('from',{}).get('emailAddress',{}).get('address')}, Original Message ID: {message.get('id')}")
            except requests.exceptions.RequestException as e:
                logger.exception(f"Error checking for false negatives for {mailbox_address}: {e}")
            except Exception as e:
                logger.exception(f"A general error occurred in check_for_fn_feedback for {mailbox_address}: {e}")
        else:
            logger.error(f"Could not get access token for false negative check for {mailbox_address}.")
        time.sleep(parse_interval(config.SCHEDULING_INTERVALS.get("fn_feedback_loop", "5m")))
        access_token_queue.put(email_client.get_access_token()) #Refresh the token

def main_email_loop(mailbox_address: str, access_token_queue: queue.Queue, email_client: EmailClient, complaint_processor: ComplaintProcessor):
    """Main loop to process emails for a specific mailbox."""
    delta_tokens = load_delta_tokens()
    current_delta_token = delta_tokens.get(mailbox_address)

    while True:
        access_token = access_token_queue.get()
        if access_token:
            try:
                emails, new_delta_token = email_client.get_emails(access_token, mailbox_address, current_delta_token, config.EMAIL_FILTER)
                if emails:
                    for message in emails:
                        complaint_processor.process_email(message, access_token, mailbox_address) # Pass mailbox_address (user_id)

                if new_delta_token:
                    delta_tokens[mailbox_address] = new_delta_token
                    save_delta_tokens(delta_tokens)
                    current_delta_token = new_delta_token

            except requests.exceptions.RequestException as e:
                logger.error(f"Error retrieving emails for {mailbox_address}: {e}")
                if e.response is not None:
                    logger.error(f"Response content: {e.response.text}") # Log the error response for debugging
            except Exception as e:
                logger.exception(f"A general error occurred in main email loop for {mailbox_address}: {e}")
        else:
            logger.error(f"Could not get access token for main email loop for {mailbox_address}.")

        time.sleep(parse_interval(config.SCHEDULING_INTERVALS.get("main_loop", "5m")))
        access_token_queue.put(email_client.get_access_token()) # refresh the token

def main():
    email_client = EmailClient()
    access_token = email_client.get_access_token()
    if not access_token:
        logger.error("Could not get initial access token. Exiting.")
        return

    access_token_queue = queue.Queue()
    access_token_queue.put(access_token)

    complaint_processor = ComplaintProcessor(email_client)

    threads = []

    for mailbox in config.MONITORED_MAILBOXES:
        # Mailbox processing thread
        mailbox_thread = threading.Thread(target=main_email_loop, args=(mailbox, access_token_queue, email_client, complaint_processor))
        threads.append(mailbox_thread)
        mailbox_thread.start()

        # Feedback loop threads (per mailbox)
        fp_thread = threading.Thread(target=check_for_fp_feedback, args=(mailbox, access_token_queue, email_client))
        fn_thread = threading.Thread(target=check_for_fn_feedback, args=(mailbox, access_token_queue, email_client))
        threads.extend([fp_thread, fn_thread])
        fp_thread.start()
        fn_thread.start()

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        logger.info("Shutting down...")
    finally:
        for thread in threads:
            thread.join()
        logger.info("All threads finished.")
    logger.info("Exiting main process.")

if __name__ == "__main__":
    main()