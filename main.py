from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
import queue
import re
import sys
import threading
import time

import requests
from loguru import logger

from .config_loader import Config
from .email_client import EmailClient
from .complaint_processor import ComplaintProcessor
from .utils import parse_interval, load_delta_tokens, save_delta_tokens
from .file_observer import FileObserver, FileEventHandler

# Configure logging
logger.add("complaint_processor.log", rotation="10 MB", level="INFO")
logger.add(
    sys.stdout, level="DEBUG", format="{time:YYYY-MM-DD HH:mm:ss} | {level} | {message}"
)


config = Config("config.json", "config_schema.json")
shared_resource_lock = threading.Lock()
config_reload_event = threading.Event() # signal reload of config

def check_for_feedback(mailbox_address: str, access_token_queue: queue.Queue, email_client: EmailClient, feedback_type: str):
    processed_message_ids = set()
    interval_key = f"{feedback_type}_feedback_loop"
    while True:
        access_token = access_token_queue.get()
        if access_token:
            try:
                with shared_resource_lock:
                  last_checked = time.time() - parse_interval(config.scheduling_intervals.get(interval_key, "5m"))

                if config_reload_event.is_set():
                    logger.info(f"Configuration reload detected in {feedback_type} thread for {mailbox_address}.")
                    config_reload_event.clear()

                if (time.time() - last_checked >= parse_interval(config.scheduling_intervals.get(interval_key, "5m"))):
                    graph_api_url = (f"https://graph.microsoft.com/v1.0/users/{mailbox_address}/mailFolders/Inbox/messages")
                    headers = {
                        "Authorization": f"Bearer {access_token}",
                        "Content-Type": "application/json",
                    }
                    # Filter for messages received since the last check
                    with shared_resource_lock:
                      filter_query = (
                          f"receivedDateTime ge "
                          f"{datetime.fromtimestamp(last_checked).astimezone().isoformat()}"
                      )
                      params = {"$filter": filter_query, "$top": config.top_emails}

                    response = requests.get(graph_api_url, headers=headers, params=params)
                    response.raise_for_status()
                    messages = response.json().get("value", [])

                    for message in messages:
                        message_id = message.get("id")
                        if message_id not in processed_message_ids:
                            if feedback_type == "fp":
                                match = re.search(
                                    r"X-Complaint-Processor: Processed-v1.0; ID=(.*?);",
                                    message["body"]["content"],
                                )
                                if match:
                                    email_id = match.group(1)
                                    logger.info(
                                        f"False Positive detected for {mailbox_address}: "
                                        f"Email ID: {email_id}, Subject: {message.get('subject')}, "
                                        f"Original Message ID: {message_id}"
                                    )
                                    processed_message_ids.add(message_id)
                            elif feedback_type == "fn":
                                with shared_resource_lock:
                                  distribution_list_email = config.distribution_list_email
                                if message.get("toRecipients") and any(
                                    address.get("emailAddress", {}).get("address")
                                    == distribution_list_email
                                    for address in message.get("toRecipients", [])
                                ):
                                    logger.info(
                                        f"Potential False Negative Detected for {mailbox_address}: "
                                        f"Subject: {message.get('subject')}, "
                                        f"From: {message.get('from', {}).get('emailAddress', {}).get('address')}, "
                                        f"Original Message ID: {message_id}"
                                    )
                                    processed_message_ids.add(message_id)
                    last_checked = time.time()

            except requests.exceptions.RequestException as e:
                logger.exception(
                    f"Error checking for {feedback_type} feedback for {mailbox_address}: {e}"
                )
            except Exception as e:
                logger.exception(
                    f"A general error occurred in check_for_{feedback_type}_feedback for {mailbox_address}: {e}"
                )
        else:
            logger.error(
                f"Could not get access token for {feedback_type} feedback check for {mailbox_address}."
            )

        time.sleep(parse_interval(config.scheduling_intervals.get(interval_key, "5m")))
        access_token_queue.put(email_client.get_access_token())


def main_email_loop(mailbox_address: str, access_token_queue: queue.Queue, email_client: EmailClient, complaint_processor: ComplaintProcessor):
    """Main loop to process emails for a specific mailbox"""
    while True:
        access_token = access_token_queue.get()
        if access_token:
            # Use a try block to handle potential exceptions
            try:
                with shared_resource_lock:
                  delta_tokens = load_delta_tokens(config)
                  current_delta_token = delta_tokens.get(mailbox_address)

                if config_reload_event.is_set():
                    logger.info(f"Configuration reload detected in main email loop for {mailbox_address}.")
                    complaint_processor.reload_keywords()
                    complaint_processor.reload_sentiment_pipeline()
                    config_reload_event.clear()

                with shared_resource_lock:
                    emails, new_delta_token = email_client.get_emails(
                        access_token, mailbox_address, current_delta_token, config.email_filter
                    )

                if emails:
                    for message in emails:
                        complaint_processor.process_email(message, access_token, mailbox_address)

                if new_delta_token:
                    delta_tokens[mailbox_address] = new_delta_token
                    try:
                        save_delta_tokens(config, delta_tokens)  # Added try-except block
                    except Exception as e:
                        logger.exception(f"Error saving delta tokens: {e}")
                    current_delta_token = new_delta_token

            except requests.exceptions.RequestException as e:
                logger.error(f"Error retrieving emails for {mailbox_address}: {e}")
                if e.response is not None:
                    logger.error(
                        f"Response content: {e.response.text}"
                    )  # Log the error response for debugging
            except Exception as e:
                logger.exception(
                    f"A general error occurred in main email loop for {mailbox_address}: {e}"
                )
        else:
            logger.error(
                f"Could not get access token for main email loop for {mailbox_address}."
            )

        with shared_resource_lock:
          time.sleep(parse_interval(config.scheduling_intervals.get("main_loop", "5m")))
        access_token_queue.put(email_client.get_access_token())  # refresh the token

class ConfigReloadHandler(FileEventHandler):
    def __init__(self, config: Config):
        self.config = config

    def on_modified(self, path):
        """Handle the configuration file modification event"""
        try:
            self.config.update_config()
            config_reload_event.set()
        except Exception as e:
            logger.exception(f"Error reloading config: {e}")

def config_reload_thread(config: Config, stop_event: threading.Event):
    """Thread to handle configuration reloading"""
    config_handler = ConfigReloadHandler(config)
    observer = FileObserver(config.config_file, config.retry_delay, config_handler)
    observer.start()

    while not stop_event.is_set():
        time.sleep(1)  # Check for stop event periodically

    observer.stop()
    logger.info("Configuration reload thread stopped.")

def main():
    email_client = EmailClient(config)
    complaint_processor = ComplaintProcessor(email_client, config)

    access_token = email_client.get_access_token()
    if not access_token:
        logger.error("Could not get initial access token. Exiting.")
        return

    access_token_queue = queue.Queue()
    access_token_queue.put(access_token)

    # Create and start the config reload thread
    stop_config_thread_event = threading.Event()
    config_thread = threading.Thread(
        target=config_reload_thread, args=(config, stop_config_thread_event)
    )
    config_thread.start()

    num_threads = len(config.monitored_mailboxes) * 3  # 3 tasks per mailbox
    with ThreadPoolExecutor(max_workers=num_threads) as executor:
        futures = []
        for mailbox in config.monitored_mailboxes:
            # Submit tasks to the thread pool
            futures.append(
                executor.submit(
                    main_email_loop,
                    mailbox,
                    access_token_queue,
                    email_client,
                    complaint_processor,
                )
            )
            futures.append(
                executor.submit(
                    check_for_feedback, mailbox, access_token_queue, email_client, "fp"
                )
            )
            futures.append(
                executor.submit(
                    check_for_feedback, mailbox, access_token_queue, email_client, "fn"
                )
            )

        try:
            # Monitor the futures for exceptions
            for future in futures:
                try:
                    future.result()  # This will raise any exceptions that occurred in the thread
                except Exception as e:
                    logger.error(f"Thread raised an exception: {e}")
        except KeyboardInterrupt:
            logger.info("Shutting down...")
        finally:
            executor.shutdown(wait=False)
            stop_config_thread_event.set()  # Signal the config thread to stop
            config_thread.join()  # Wait for the config thread to finish
            email_client._save_cache()  # Save the token cache
            logger.info("Exiting main process.")
