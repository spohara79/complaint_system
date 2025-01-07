import requests
from msal import ConfidentialClientApplication, SerializableTokenCache
from typing import Optional, List, Dict, Any, Tuple
from urllib.parse import quote, urlencode
from datetime import datetime
from .config_loader import Config
from loguru import logger
import time
import os

class EmailClient:
    """Client for interacting with Microsoft Graph API"""

    def __init__(self, config: Config):
        self.config = config
        self.cache = SerializableTokenCache()  # Create a token cache
        self.cert_path = config.cert_path
        self.cert_data = None
        self.private_key = None
        self.private_key_path = config.private_key_path
        self._load_keys()
        
        self.app = ConfidentialClientApplication(
            config.client_id,
            authority=config.authority,
            #client_secret=config.client_secret,
            client_credential = {
                "private_key": self.private_key,
                "thumbprint": self.config.cert_thumbprint,
                "public_certificate": cert_data
            },
            token_cache=self.cache  # Pass the cache to the app
        )
        self.distribution_list_email = self.config.distribution_list_email
        self.scopes = self.config.scopes
        self.max_retries = self.config.max_retries
        self.retry_delay = self.config.retry_delay
        self._load_cache()
        self.token_cache = self.config.delta_token_file

def _load_keys(self):
        """Loads the cert and private key from file"""
        try:
            if os.path.exists(self.config.cert_path):
                with open(self.config.cert_path, "r") as cert_file:
                    self.cert_data = cert_file.read()
        except Exception as e:
            logger.error(f"Failed to load certificate: {e}")
    
        try:
            if os.path.exists(self.config.private_key_path):
                with open(self.config.private_key_path, "r") as key_file:
                    self.private_key = key_file.read()
        except Exception as e:
            logger.error(f"Failed to load private key: {e}")
    
    def _load_cache(self):
        """Loads the token cache from file"""
        try:
            if os.path.exists(self.token_cache):
                with open(self.token_cache, "r") as cache_file:
                    self.cache.deserialize(cache_file.read())
        except Exception as e:
            logger.error(f"Failed to load token cache: {e}")

    def _save_cache(self):
        """Saves the token cache to file"""
        try:
            if self.cache.has_state_changed:
                with open(self.token_cache, "w") as cache_file:
                    cache_file.write(self.cache.serialize())
        except Exception as e:
            logger.error(f"Failed to save token cache: {e}")

    def _make_graph_api_request(self, url, headers, method="GET", json_data=None) -> requests.Response:
        """Helper function to make Graph API requests with retries"""
        for attempt in range(self.max_retries):
            try:
                if method == "GET":
                    response = requests.get(url, headers=headers)
                elif method == "POST":
                    response = requests.post(url, headers=headers, json=json_data)
                else:
                    raise ValueError(f"Invalid HTTP method: {method}")
                response.raise_for_status() 
                return response
            except requests.exceptions.RequestException as e:
                if attempt < self.max_retries - 1:
                    logger.warning(
                        f"Graph API request failed (attempt {attempt + 1}/{self.max_retries}): {e}. Retrying in {self.retry_delay} seconds...")
                    time.sleep(self.retry_delay)
                else:
                    logger.error(f"Graph API request failed after {self.max_retries} attempts: {e}")
                    raise
            except Exception as e:
                logger.exception(f"Unexpected error making Graph API Request: {e}")
                raise

    def get_access_token(self) -> Optional[str]:
        """Acquires an access token for the Microsoft Graph API, leveraging the token cache"""
        try:
            # Attempt to get the token from the cache
            accounts = self.app.get_accounts()
            result = None
            if accounts:
                result = self.app.acquire_token_silent(self.scopes, account=accounts[0])
            # If silent acquisition fails or no token in cache, acquire a new one
            if not result:
                result = self.app.acquire_token_for_client(scopes=self.scopes)
                self._save_cache()  # Save the cache after acquiring a new token

            if "access_token" in result:
                return result["access_token"]
            else:
                logger.error(f"MSAL Error: {result.get('error')}, Description: {result.get('error_description')}")
                return None
        except Exception as e:
            logger.exception("Error acquiring access token")
            return None

    def _build_filter_query(self, email_filter: Optional[Dict]) -> str:
        """Builds the $filter query parameter for Graph API"""
        filter_parts = []
        if email_filter:
            if "from_domain" in email_filter and email_filter["from_domain"]:
                filter_parts.append(f"from/emailAddress/address eq '{email_filter['from_domain']}'")
            if "start_date" in email_filter and email_filter["start_date"]:
                try:
                    start_date = datetime.fromisoformat(email_filter["start_date"].replace('Z', '+00:00'))
                    filter_parts.append(f"receivedDateTime ge {start_date.isoformat()}")
                except ValueError:
                    logger.error("Invalid start_date format. Use ISO 8601 format (YYYY-MM-DDTHH:mm:ssZ).")
            if "subject_contains" in email_filter and email_filter["subject_contains"]:
                filter_parts.append(f"contains(subject,'{email_filter['subject_contains']}')")

        return " and ".join(filter_parts) if filter_parts else ""

    def get_emails(self, access_token: str, mailbox_address: str, delta_token: Optional[str] = None,
                   email_filter: Optional[Dict] = None) -> Tuple[List[dict], Optional[str]]:
        """Retrieves emails from a specified mailbox using delta queries with optional filtering"""
        url = f"https://graph.microsoft.com/v1.0/users/{mailbox_address}/messages"
        query_params = {}
        headers = {"Authorization": f"Bearer {access_token}"}

        if delta_token:
            query_params["$deltaToken"] = quote(delta_token)
        else:
            query_params["$select"] = "sender,subject,body,toRecipients,from,id,receivedDateTime"
            query_params["$top"] = self.config.get("top_emails", 50)

            filter_query = self._build_filter_query(email_filter)
            if filter_query:
                query_params["$filter"] = filter_query

        url += "?" + urlencode(query_params)

        try:
            response = self._make_graph_api_request(url, headers)
            response_json = response.json()
            emails = response_json.get("value", [])
            next_link = response_json.get("@odata.nextLink")
            delta_link = response_json.get("@odata.deltaLink")
            while next_link:
                response = self._make_graph_api_request(next_link, headers)
                response_json = response.json()
                emails.extend(response_json.get("value", []))
                next_link = response_json.get("@odata.nextLink")
                delta_link = response_json.get("@odata.deltaLink")

            final_delta_token = None
            if delta_link:
                final_delta_token = delta_link.split("=")[-1]
            return emails, final_delta_token

        except requests.exceptions.RequestException as e:
            logger.error(f"Error retrieving emails: {e}")
            return [], None

    def _create_forward_message_payload(self, original_message: Dict[str, Any]) -> Dict[str, Any]:
        """Creates the payload for forwarding a message"""
        return {
            "message": {
                "subject": f"FW: {original_message['subject']}",
                "toRecipients": [{"emailAddress": {"address": self.distribution_list_email}}],
                "body": {"content": original_message["body"]["content"]},
                "attachments": original_message.get("attachments", [])
            },
            "saveToSentItems": False
        }

    def send_message_to_distribution_list(self, access_token: str, user_id: str, message_id: str):
        """Sends a copy of the specified message to the distribution list"""
        try:
            get_message_url = f"https://graph.microsoft.com/v1.0/users/{user_id}/messages/{message_id}"
            headers: Dict[str, str] = {
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json"
            }
            message_response = self._make_graph_api_request(get_message_url, headers)
            original_message: Dict[str, Any] = message_response.json()

            send_data = self._create_forward_message_payload(original_message)
            send_message_url = f"https://graph.microsoft.com/v1.0/users/{user_id}/sendMail"
            send_headers = {"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"}
            self._make_graph_api_request(send_message_url, send_headers, method="POST", json_data=send_data)

            logger.info(f"Message {message_id} forwarded to distribution list.")

        except requests.exceptions.RequestException as e:
            logger.error(f"Error forwarding message: {e}")
