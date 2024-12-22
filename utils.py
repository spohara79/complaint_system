from loguru import logger
import config
import re, json, os
from typing import List, Dict


def load_keywords_from_file(filepath: str) -> List[str]:
    """Load keywords from a file and return a list of keywords"""
    try:
        with open(filepath, "r") as f:
            return [line.strip() for line in f]
    except FileNotFoundError:
        logger.error(f"Keyword file not found: {filepath}")
        return []

def load_delta_tokens() -> Dict[str, str]:
    """Loads delta tokens from the file"""
    if os.path.exists(config.DELTA_TOKEN_FILE):
        with open(config.DELTA_TOKEN_FILE, "r") as f:
            return json.load(f)
    return {}

def save_delta_tokens(delta_tokens: Dict[str, str]):
    """Saves delta tokens to the file"""
    with open(config.DELTA_TOKEN_FILE, "w") as f:
        json.dump(delta_tokens, f)

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