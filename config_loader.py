import json
import os
from typing import Dict, Any
from jsonschema import validate, ValidationError
from loguru import logger

class Config:

    def __init__(self, config_file, schema_file):
        self.config_file = config_file
        self.schema_file = schema_file
        self._config_data = {}
        self._last_config_load_time = 0
        self._load_config()

    def _is_config_outdated(self):
        """Checks if the configuration file has been modified since the last load"""
        if not os.path.exists(self.config_file):
            return True
        try:
            current_mod_time = os.path.getmtime(self.config_file)
            return current_mod_time > self._last_config_load_time
        except OSError as e:
            logger.error(f"Error checking config file modification time: {e}")
            return False
        except Exception as e:
            logger.exception(f"Unexpected error checking config file modification time: {e}")
            return False

    def _load_schema(self):
        """Loads the JSON schema from the schema file"""
        try:
            with open(self.schema_file, "r") as f:
                return json.load(f)
        except FileNotFoundError:
            logger.error(f"Schema file '{self.schema_file}' not found.")
            return None
        except json.JSONDecodeError as e:
            logger.error(f"Error decoding schema file: {e}")
            return None
        except Exception as e:
            logger.exception(f"Unexpected error loading schema: {e}")
            return None

    def _load_config(self):
        """Loads and validates the configuration"""
        schema = self._load_schema()
        if schema is None:
            logger.error("No schema loaded. Cannot load config.")
            return

        try:
            with open(self.config_file, "r", encoding="utf-8") as f:
                config_data = json.load(f)

            validate(instance=config_data, schema=schema)
            self._config_data = config_data
            self._last_config_load_time = os.path.getmtime(self.config_file)
            logger.info(
                f"Configuration loaded from {self.config_file} and validated successfully."
            )

        except FileNotFoundError:
            logger.error(f"Configuration file '{self.config_file}' not found.")
        except json.JSONDecodeError as e:
            logger.error(f"Error decoding configuration file: {e}")
        except ValidationError as e:
            logger.error(f"Configuration validation error: {e}")
        except OSError as e:
            logger.error(f"OS Error reading configuration file: {e}")
        except Exception as e:
            logger.exception(f"An unexpected error occurred loading configuration: {e}")

    def __getattr__(self, name):
        if name in self._config_data:
            value = self._config_data[name]
            if isinstance(value, dict):
                return ConfigWrapper(value)
            else:
                return value
        raise AttributeError(f"Config key '{name}' not found.")

    def __contains__(self, item):
        return item in self._config_data
class ConfigWrapper:
    def __init__(self, config_data):
        self._config_data = config_data
    def __getattr__(self, name):
        if name in self._config_data:
            return self._config_data[name]
        raise AttributeError(f"'weights' Config key '{name}' not found.")
    def __contains__(self, item):
        return item in self._config_data
    def get(self, key, default=None):
        return self._config_data.get(key, default)
