import os
import time
import threading
from loguru import logger
from abc import ABC, abstractmethod

class FileEventHandler(ABC):  # Abstract base class
    @abstractmethod
    def on_modified(self, path):
        pass

class FileObserver:
    def __init__(self, file_path, retry_delay, event_handler: FileEventHandler):
        self.file_path = file_path
        self.retry_delay = retry_delay
        self.event_handler = event_handler
        self._stop_event = threading.Event()
        self._thread = None

    def start(self):
        """Starts the file observer"""
        if self._thread is None:
            self._thread = threading.Thread(target=self._observe)
            self._thread.start()
            logger.info(f"File observer started for: {self.file_path}")
        else:
            logger.warning("File observer already started.")

    def stop(self):
        """Stops the file observer"""
        if self._thread:
            self._stop_event.set()
            self._thread.join()
            self._thread = None
            self._stop_event.clear()
            logger.info(f"File observer stopped for: {self.file_path}")
        else:
            logger.warning("File observer not running.")

    def _observe(self):
        """Monitors the file for modifications"""
        last_modified = None
        while not self._stop_event.is_set():
            try:
                if not os.path.exists(self.file_path):
                    logger.warning(f"Config file not found: {self.file_path}")
                    last_modified = None
                    time.sleep(self.retry_delay)
                    continue

                current_modified = os.path.getmtime(self.file_path)

                if last_modified is None:
                    last_modified = current_modified
                    logger.debug(f"Initial file modification time recorded: {last_modified}")
                elif current_modified > last_modified:
                    logger.info(f"Config file modified. Triggering event handler for: {self.file_path}")
                    try:
                        self.event_handler.on_modified(self.file_path)
                    except Exception as e:
                        logger.exception(f"Error in event handler: {e}")
                    last_modified = current_modified
                elif current_modified < last_modified:
                    logger.debug(
                        f"Config file modification time went backwards. Possible file replacement: {self.file_path}"
                    )
                    last_modified = current_modified

            except OSError as e:
                logger.error(f"OS error accessing config file {self.file_path}: {e}")
                time.sleep(self.retry_delay)
            except Exception as e:
                logger.exception(f"Unexpected error in file observer: {e}")
                time.sleep(self.retry_delay)
            time.sleep(self.retry_delay)