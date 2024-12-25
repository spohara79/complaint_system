from loguru import logger
from .config_loader import Config
import re, json, os
from typing import List, Dict

def load_keywords_from_file(filepath: str) -> List[str]:
    """Load keywords from a file"""
    try:
        with open(filepath, "r", encoding="utf-8") as f: #Explicit encoding
            return [line.strip() for line in f]
    except FileNotFoundError:
        logger.error(f"Keyword file not found: {filepath}")
        return []
    except OSError as e:
        logger.error(f"Error opening keyword file {filepath}: {e}")
        return []
    except Exception as e:
        logger.exception(f"Unexpected error loading keywords from {filepath}: {e}")
        return []

def load_delta_tokens(config: Config) -> Dict[str, str]:
    """Loads delta tokens from file"""
    delta_token_path = config.delta_token_path
    try:
        if os.path.exists(delta_token_path):
            with open(delta_token_path, "r", encoding="utf-8") as f: #Explicit encoding
                return json.load(f)
        return {}
    except FileNotFoundError:
        logger.warning(f"Delta token file not found: {delta_token_path}. Starting with empty tokens.")
        return {}
    except json.JSONDecodeError as e:
        logger.error(f"Error decoding delta token file: {e}")
        return {}
    except OSError as e:
        logger.error(f"Error opening delta token file {delta_token_path}: {e}")
        return {}
    except Exception as e:
        logger.exception(f"Unexpected error loading delta tokens: {e}")
        return {}


def save_delta_tokens(config: Config, delta_tokens: Dict[str, str]):
    """Saves delta tokens to the file"""
    delta_token_path = config.delta_token_path
    try:
        with open(delta_token_path, "w", encoding="utf-8") as f: #Explicit encoding
            json.dump(delta_tokens, f, indent=4) # Add indentation for readability
    except OSError as e:
        logger.error(f"Error saving delta tokens to {delta_token_path}: {e}")
    except TypeError as e:
        logger.error(f"Type error saving delta tokens to {delta_token_path}. Check data type of delta_tokens: {e}")
    except Exception as e:
        logger.exception(f"Unexpected error saving delta tokens: {e}")

def parse_interval(interval_str: str) -> int:
    """Parses a time interval string (e.g., '30s', '5m', '1h') into seconds"""
    unit = interval_str[-1] # Get the last character
    try:
        value = int(interval_str[:-1]) # Get all characters except the last one
    except ValueError:
        raise ValueError("Invalid time interval format. Use a number followed by 's', 'm', or 'h'.")

    if unit == "s":
        return value
    elif unit == "m":
        return value * 60
    elif unit == "h":
        return value * 3600
    else:
        raise ValueError("Invalid time unit. Use 's', 'm', or 'h'.")

def clean_email(email_str: str) -> str:
    """Cleans an email string by removing HTML tags and extra spaces"""
    clean_text = re.sub('<[^<]+?>', '', email_str)  # Remove HTML tags
    clean_text = re.sub(r'\s+', ' ', clean_text).strip()  # Remove extra spaces
    return clean_text.lower()