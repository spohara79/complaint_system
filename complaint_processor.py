import re
from typing import Dict, List, Any
from transformers import pipeline
from .email_client import EmailClient
from .utils import clean_email, load_keywords_from_file
import config
from loguru import logger

try:
    classifier = pipeline("sentiment-analysis", model=config.SENTIMENT_MODEL)
except Exception as e:
    logger.error(f"Failed to initialize sentiment analysis pipeline: {e}")
    exit(1)

class ComplaintProcessor:
    def __init__(self, email_client: EmailClient):
        self.email_client = email_client
        self.complaint_keywords = load_keywords_from_file(config.COMPLAINT_KEYWORDS_FILE)
        self.subject_keywords = load_keywords_from_file(config.SUBJECT_KEYWORDS_FILE)
        self.urgency_keywords = load_keywords_from_file(config.URGENCY_KEYWORDS_FILE)
        self.negation_keywords = load_keywords_from_file(config.NEGATION_KEYWORDS_FILE)

    def keyword_match(self, cleaned_body: str, cleaned_subject: str) -> bool:
        """Determines if an email is a complaint based on keyword matching"""
        score = 0
        negation_weight = config.WEIGHTS.get("negation", -0.5)

        # Keyword and Negation Handling (Body)
        for keyword in self.complaint_keywords:
            if re.search(r'\b' + re.escape(keyword) + r'\b', cleaned_body):
                if any(re.search(r'\b' + re.escape(negation) + r'\b\s+(?:very\s+)?' + re.escape(keyword), cleaned_body) for negation in self.negation_keywords):
                    score += negation_weight
                else:
                    score += config.WEIGHTS["body_keyword"]
                break

        # Simple Keyword Handling (Subject)
        for keyword in self.subject_keywords:
            if re.search(r'\b' + re.escape(keyword) + r'\b', cleaned_subject):
                score += config.WEIGHTS["subject_keyword"]
                break

        # Simple Urgency Heuristics (Body and Subject)
        for indicator in self.urgency_keywords:
            if re.search(r'\b' + re.escape(indicator) + r'\b', cleaned_body) or re.search(r'\b' + re.escape(indicator) + r'\b', cleaned_subject):
                score += config.WEIGHTS["urgency"]
                break

        return score >= config.COMPLAINT_THRESHOLD

    def is_complaint(self, email_body: str, email_subject: str, fallback=True) -> bool:
        """
        Checks if an email is a potential complaint based on keywords and sentiment

        Args:
            email_subject (str): Subject line of the email
            email_body (str): Body content of the email

        Returns:
            bool: True if the email is likely a complaint, False otherwise
        """
        cleaned_body = clean_email(email_body)
        cleaned_subject = clean_email(email_subject)

        try:
            sentiment_result = classifier(cleaned_body)[0]
            sentiment_label: str = sentiment_result['label']
            sentiment_score: float = sentiment_result['score']
        except Exception as e:
            logger.error(f"Error during sentiment analysis: {e}")
            if fallback:
                return self.keyword_match(cleaned_body, cleaned_subject)
            return False

        if sentiment_label == "NEGATIVE" and sentiment_score > config.COMPLAINT_THRESHOLD:
            return True

        if fallback:
            return self.keyword_match(cleaned_body, cleaned_subject)

        return False

    def process_email(self, message: Dict[str, Any], access_token: str, user_id: str) -> None:
        """Processes an email message for Sentiment Analysis and Complaint Detection"""
        subject: str = message.get("subject", "No Subject")
        receiver: str = message.get("toRecipients", [{}])[0].get("emailAddress", {}).get("address", "No Receiver")
        sender: str = message.get("from", {}).get("emailAddress", {}).get("address", "No Sender")
        body_content: str = message["body"]["content"]
        message_id = message.get('id')

        # Add a custom header to the email for feedback learning
        header = f"X-Complaint-Processor: Processed-v1.0; ID={message_id};"
        message["body"]["content"] = header + message["body"]["content"]

        for key, values in config.EXCLUSIONS.items():
            if key == 'from':
                for value in values:
                    if re.match(value, sender):
                        logger.info(f"Excluded sender: {sender}")
                        return
            elif key == 'subject':
                for value in values:
                    if re.match(value, subject):
                        logger.info(f"Excluded subject: {subject}")
                        return
            elif key == 'toRecipients':
                for value in values:
                    if re.match(value, receiver):
                        logger.info(f"Excluded recipient: {receiver}")
                        return

        if self.is_complaint(body_content, subject):
            logger.info(f"Complaint detected: Subject: {subject}, From: {sender}, Message ID: {message_id}")
            try:
                self.email_client.send_message_to_distribution_list(access_token, user_id, message_id)
                logger.info("Complaint forwarded to distribution list.")
            except Exception as send_error:
                logger.exception(f"Error forwarding complaint: {send_error}")