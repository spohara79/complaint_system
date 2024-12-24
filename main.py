from .email_client import EmailClient
from .complaint_processor import ComplaintProcessor
from .utils import parse_interval, load_delta_tokens, save_delta_tokens
from .config_loader import Config, start_config_watcher, stop_config_watcher
import time
import queue
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

from loguru import logger
import requests

# Configure logging
logger.add("complaint_processor.log", rotation="10 MB", level="INFO")
logger.add(sys.stdout, level="DEBUG", format="{time:YYYY-MM-DD HH:mm:ss} | {level} | {message}")

config = Config("config.json", "config_schema.json")  # Create the config object

def check_for_fp_feedback(mailbox_address: str, access_token_queue: queue.Queue, email_client: EmailClient):
    """Checks a mailbox for false positive feedback messages."""
    processed_message_ids = set()  # Keep track of processed messages
    last_checked = time.time() - parse_interval(config.scheduling_intervals.get("fp_feedback_loop", "5m"))

    while True:
        access_token = access_token_queue.get()
        if access_token:
            try:
                if time.time() - last_checked >= parse_interval(config.scheduling_intervals.get("fp_feedback_loop", "5m")):
                    graph_api_url = f"https://graph.microsoft.com/v1.0/users/{mailbox_address}/mailFolders/Inbox/messages"
                    headers = {
                        "Authorization": f"Bearer {access_token}",
                        "Content-Type": "application/json"
                    }
                    # Filter for messages received since the last check
                    filter_query = f"receivedDateTime ge {datetime.fromtimestamp(last_checked).astimezone().isoformat()}"
                    params = {"$filter": filter_query, "$top": 10}  # Get top 10 messages

                    response = requests.get(graph_api_url, headers=headers, params=params)
                    response.raise_for_status()
                    retrieved_emails = response.json().get("value", [])

                    for message in retrieved_emails:
                        message_id = message.get("id")
                        if message_id not in processed_message_ids:
                            match = re.search(r"X-Complaint-Processor: Processed-v1.0; ID=(.*?);", message["body"]["content"])
                            if match:
                                email_id = match.group(1)
                                logger.info(
                                    f"False Positive detected for {mailbox_address}: Email ID: {email_id}, Subject: {message.get('subject')}, Original Message ID: {message_id}")
                                processed_message_ids.add(message_id)
                    last_checked = time.time()

            except requests.exceptions.RequestException as e:
                logger.exception(f"Error checking for false positives for {mailbox_address}: {e}")
            except Exception as e:
                logger.exception(f"A general error occurred in check_for_fp_feedback for {mailbox_address}: {e}")
        else:
            logger.error(f"Could not get access token for false positive check for {mailbox_address}.")

        time.sleep(parse_interval(config.scheduling_intervals.get("fp_feedback_loop", "5m")))
        access_token_queue.put(email_client.get_access_token())

def check_for_fn_feedback(mailbox_address: str, access_token_queue: queue.Queue, email_client: EmailClient):
    """Checks a mailbox for false negative feedback messages."""
    processed_message_ids = set()  # Keep track of processed messages
    last_checked = time.time() - parse_interval(config.scheduling_intervals.get("fn_feedback_loop", "5m"))

    while True:
        access_token = access_token_queue.get()
        if access_token:
            try:
                if time.time() - last_checked >= parse_interval(config.scheduling_intervals.get("fn_feedback_loop", "5m")):
                    graph_api_url = f"https://graph.microsoft.com/v1.0/users/{mailbox_address}/mailFolders/Inbox/messages"
                    headers = {
                        "Authorization": f"Bearer {access_token}",
                        "Content-Type": "application/json"
                    }
                    # Filter for messages received since the last check
                    filter_query = f"receivedDateTime ge {datetime.fromtimestamp(last_checked).astimezone().isoformat()}"
                    params = {"$filter": filter_query, "$top": 10}  # Get top 10 messages

                    response = requests.get(graph_api_url, headers=headers, params=params)
                    response.raise_for_status()
                    messages = response.json().get("value", [])

                    for message in messages:
                        message_id = message.get("id")
                        if message_id not in processed_message_ids:
                            if message.get("toRecipients") and any(
                                    address.get("emailAddress", {}).get("address") == config.distribution_list_email for
                                    address in message.get("toRecipients", [])):
                                logger.info(
                                    f"Potential False Negative Detected for {mailbox_address}: Subject: {message.get('subject')}, From: {message.get('from', {}).get('emailAddress', {}).get('address')}, Original Message ID: {message_id}")
                                processed_message_ids.add(message_id)
                    last_checked = time.time()

            except requests.exceptions.RequestException as e:
                logger.exception(f"Error checking for false negatives for {mailbox_address}: {e}")
            except Exception as e:
                logger.exception(f"A general error occurred in check_for_fn_feedback for {mailbox_address}: {e}")
        else:
            logger.error(f"Could not get access token for false negative check for {mailbox_address}.")

        time.sleep(parse_interval(config.scheduling_intervals.get("fn_feedback_loop", "5m")))
        access_token_queue.put(email_client.get_access_token())  # Refresh the token

def main_email_loop(mailbox_address: str, access_token_queue: queue.Queue, email_client: EmailClient, complaint_processor: ComplaintProcessor):
    """Main loop to process emails for a specific mailbox."""
    delta_tokens = load_delta_tokens(config)
    current_delta_token = delta_tokens.get(mailbox_address)

    while True:
        access_token = access_token_queue.get()
        if access_token:
            try:
                emails, new_delta_token = email_client.get_emails(access_token, mailbox_address, current_delta_token, config.email_filter)
                if emails:
                    for message in emails:
                        complaint_processor.process_email(message, access_token, mailbox_address) # Pass mailbox_address (user_id)

                if new_delta_token:
                    delta_tokens[mailbox_address] = new_delta_token
                    try:
                        save_delta_tokens(config, delta_tokens) # Added try-except block
                    except Exception as e:
                        logger.exception(f"Error saving delta tokens: {e}")
                    current_delta_token = new_delta_token

            except requests.exceptions.RequestException as e:
                logger.error(f"Error retrieving emails for {mailbox_address}: {e}")
                if e.response is not None:
                    logger.error(f"Response content: {e.response.text}") # Log the error response for debugging
            except Exception as e:
                logger.exception(f"A general error occurred in main email loop for {mailbox_address}: {e}")
        else:
            logger.error(f"Could not get access token for main email loop for {mailbox_address}.")

        time.sleep(parse_interval(config.scheduling_intervals.get("main_loop", "5m")))
        access_token_queue.put(email_client.get_access_token()) # refresh the token

def main():
    observer = start_config_watcher(config) #Start the watcher, passing the config object
    email_client = EmailClient(config) # Pass the config object to EmailClient
    complaint_processor = ComplaintProcessor(email_client, config) #Pass the config object to ComplaintProcessor

    access_token = email_client.get_access_token()
    if not access_token:
        logger.error("Could not get initial access token. Exiting.")
        return

    access_token_queue = queue.Queue()
    access_token_queue.put(access_token)
    num_threads = len(config.monitored_mailboxes) * 3
    with ThreadPoolExecutor(max_workers=num_threads) as executor:
        futures = []
        for mailbox in config.monitored_mailboxes:
            futures.append(executor.submit(main_email_loop, mailbox, access_token_queue, email_client, complaint_processor))
            futures.append(executor.submit(check_for_fp_feedback, mailbox, access_token_queue, email_client))
            futures.append(executor.submit(check_for_fn_feedback, mailbox, access_token_queue, email_client))

        try:
            # Monitor the futures for exceptions
            for future in futures:
                try:
                    future.result()  # This will raise any exceptions that occurred in the thread
                except Exception as e:
                    logger.error(f"Thread raised an exception: {e}")
        except KeyboardInterrupt:
            logger.info("Shutting down...")
            # No need to manually stop threads when using ThreadPoolExecutor
        finally:
            executor.shutdown(wait=True)
            stop_config_watcher(observer)
            email_client._save_cache()  # Save the token cache
            logger.info("Exiting main process.")


if __name__ == "__main__":
    main()