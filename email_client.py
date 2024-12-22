import requests
from msal import ConfidentialClientApplication
from typing import Optional, List, Dict, Any, Tuple
from urllib.parse import quote, urlencode
import config
from datetime import datetime
from loguru import logger

class EmailClient:
    """Client for interacting with Microsoft Graph API"""

    def __init__(self):
        self.app = ConfidentialClientApplication(
            config.CLIENT_ID,
            authority=config.AUTHORITY,
            client_secret=config.CLIENT_SECRET
        )

    def get_access_token(self) -> Optional[str]:
        """Acquires an access token for the Microsoft Graph API"""
        try:
            result = self.app.acquire_token_for_client(scopes=config.SCOPES)
            if "access_token" in result:
                return result["access_token"]
            else:
                logger.error(f"MSAL Error: {result.get('error')}, Description: {result.get('error_description')}")
                return None
        except Exception as e:
            logger.exception("Error acquiring access token")
            return None
    
    def get_emails(self, access_token: str, mailbox_address: str, delta_token: Optional[str] = None, email_filter: Optional[Dict] = None) -> Tuple[List[dict], Optional[str]]:
        """Retrieves emails using delta queries with filtering for single mailbox"""

        url = f"https://graph.microsoft.com/v1.0/users/{mailbox_address}/messages"  # Use mailbox_address here

        query_params = {}

        if delta_token:
            query_params["$deltaToken"] = quote(delta_token)
        else:
            query_params["$select"] = "sender,subject,body,toRecipients,from,id,receivedDateTime"  # Added receivedDateTime to select
            query_params["$top"] = 50

            # Apply filters
            filter_parts = []
            if email_filter:
                if "from_domain" in email_filter:
                    filter_parts.append(f"from/emailAddress/address eq '{email_filter['from_domain']}'")
                if "start_date" in email_filter:
                    try:
                        start_date = datetime.fromisoformat(email_filter["start_date"].replace('Z', '+00:00'))
                        filter_parts.append(f"receivedDateTime ge {start_date.isoformat()}")
                    except ValueError:
                        logger.error("Invalid start_date format. Use ISO 8601 format (YYYY-MM-DDTHH:mm:ssZ).")
                if "subject_contains" in email_filter:
                    filter_parts.append(f"contains(subject,'{email_filter['subject_contains']}')")

            if filter_parts:
                query_params["$filter"] = " and ".join(filter_parts)

        url += "?" + urlencode(query_params)

        headers = {"Authorization": f"Bearer {access_token}"}

        try:
            response = requests.get(url, headers=headers)
            response.raise_for_status()
            emails = response.json().get("value", [])

            next_link = response.json().get("@odata.nextLink")
            delta_link = response.json().get("@odata.deltaLink")

            if next_link:
                all_emails = emails
                while next_link:
                    next_response = requests.get(next_link, headers=headers)
                    next_response.raise_for_status()
                    next_emails = next_response.json().get("value", [])
                    all_emails.extend(next_emails)
                    next_link = next_response.json().get("@odata.nextLink")
                return all_emails, delta_link
            elif delta_link:
                return emails, delta_link
            else:
                return emails, None
        except requests.exceptions.RequestException as e:
            logger.error(f"Error retrieving emails: {e}")
            return [], None
        
def send_message_to_distribution_list(self, access_token: str, user_id: str, message_id: str, delete_original: bool = True):
    """
    Sends a copy of the specified message to the distribution list

    Args:
        access_token (str): Microsoft Graph API access token
        user_id (str): User ID of the mailbox containing the message
        message_id (str): ID of the message to forward
        delete_original (bool, optional): Whether to delete the original message after forwarding. Defaults to True.
    """
    try:
        # Construct the URL to GET the original message
        get_message_url = f"https://graph.microsoft.com/v1.0/users/{user_id}/messages/{message_id}"
        headers: Dict[str, str] = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json"
        }
        message_response = requests.get(get_message_url, headers=headers)
        message_response.raise_for_status()
        original_message: Dict[str, Any] = message_response.json()

        # Construct the data for sending the message
        send_message_url = f"https://graph.microsoft.com/v1.0/users/{user_id}/sendMail"
        send_data: Dict[str, Any] = {
            "message": {
                "subject": f"FW: {original_message['subject']}",  # Forward indicator in subject
                "toRecipients": [{ "emailAddress": { "address": config.DISTRIBUTION_LIST_EMAIL } }],
                "body": {
                    "content": original_message["body"]["content"]
                },
                "attachments": original_message.get("attachments", [])  # Include attachments if any
            },
            "saveToSentItems": False  # Don't save the forwarded message in Sent Items
        }

        headers = {"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"}
        send_response = requests.post(send_message_url, json=send_data, headers=headers)
        send_response.raise_for_status()

        logger.info(f"Message {message_id} forwarded to distribution list.")

        # Optionally delete the original message
        if delete_original:
            delete_url = f"https://graph.microsoft.com/v1.0/users/{user_id}/messages/{message_id}"
            delete_headers = {"Authorization": f"Bearer {access_token}"}
            requests.delete(delete_url, headers=delete_headers)
            logger.info(f"Original message {message_id} deleted.")

    except requests.exceptions.RequestException as e:
        logger.error(f"Error forwarding message: {e}")