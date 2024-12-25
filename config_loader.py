import re
from typing import Dict, Any, Tuple
from sklearn.metrics.pairwise import cosine_similarity
from transformers import pipeline, AutoTokenizer, AutoModel
from .email_client import EmailClient
from .utils import clean_email, load_keywords_from_file
from .config_loader import Config
from loguru import logger
import time
import torch

class ComplaintProcessor:
    def __init__(self, email_client: EmailClient, config: Config):
        self.email_client = email_client
        self.config = config
        self.sentiment_classifier = None
        self.tokenizer = AutoTokenizer.from_pretrained(self.config.sentiment_model)
        self.model = AutoModel.from_pretrained(self.config.sentiment_model)
        self.keyword_embeddings = self.generate_keyword_embeddings()
        self.reload_keywords()
        self.reload_sentiment_pipeline()

    def reload_sentiment_pipeline(self):
        """Attempts to initialize sentiment analysis pipeline with retries"""
        max_retries = self.config.sentiment_pipeline_max_retries
        retry_delay = self.config.sentiment_pipeline_retry_delay
        for attempt in range(max_retries):
            try:
                self.sentiment_classifier = pipeline("sentiment-analysis", model=self.config.sentiment_model)
                logger.info(f"Initialized sentiment analysis pipeline with model: {self.config.sentiment_model}")
                return
            except OSError as e:
                if attempt < max_retries - 1:
                    logger.warning(f"Error connecting to the sentiment analysis pipeline (attempt {attempt + 1}/{max_retries}): {e}. Retrying in {retry_delay} seconds...")
                    time.sleep(retry_delay)
                else:
                    logger.error(f"Failed to initialize sentiment analysis pipeline after {max_retries} attempts: {e}")
                    raise  # Re-raise the exception after all retries
            except Exception as e:
                logger.exception(f"Unexpected error during sentiment analysis pipeline initialization: {e}")
                raise

    def reload_keywords(self):
        """Loads keywords from files, sorting by length"""
        self.complaint_keywords = sorted(load_keywords_from_file(self.config.complaint_keywords_file), key=len, reverse=True)
        self.subject_keywords = sorted(load_keywords_from_file(self.config.subject_keywords_file), key=len, reverse=True)
        self.urgency_keywords = sorted(load_keywords_from_file(self.config.urgency_keywords_file), key=len, reverse=True)
        self.negation_keywords = sorted(load_keywords_from_file(self.config.negation_keywords_file), key=len, reverse=True)
        self.keyword_embeddings = self.generate_keyword_embeddings()

    def generate_keyword_embeddings(self):
        """Generates embeddings for complaint keywords"""
        keyword_embeddings = {}
        for keyword in self.complaint_keywords:
            keyword_embeddings[keyword] = self.get_embedding(keyword)
        return keyword_embeddings

    def get_embedding(self, text: str):
        """Generates an embedding for a given text"""
        inputs = self.tokenizer(text, return_tensors="pt", padding=True, truncation=True, max_length=512)
        with torch.no_grad():
            outputs = self.model(**inputs)
        # Use the average of the last hidden states as the embedding
        embeddings = outputs.last_hidden_state.mean(dim=1).squeeze().numpy()
        return embeddings

    def get_contextual_score(self, email_body: str) -> float:
        """Calculates a contextual complaint score based on keyword embeddings and email body embedding"""
        email_embedding = self.get_embedding(email_body)
        total_score = 0

        sentences = re.split(r'(?<!\w\.\w.)(?<![A-Z][a-z]\.)(?<=\.|\?)\s', email_body)

        for keyword, keyword_embedding in self.keyword_embeddings.items():
            keyword_present = False
            for sentence in sentences:
                if keyword.lower() in sentence.lower():
                    sentence_embedding = self.get_embedding(sentence)
                    similarity = cosine_similarity([keyword_embedding], [sentence_embedding])[0][0]
                    total_score += similarity
                    keyword_present = True

            if keyword_present:
                # Add similarity between keyword and overall email body
                overall_similarity = cosine_similarity([keyword_embedding], [email_embedding])[0][0]
                total_score += overall_similarity

        return total_score

    def get_sentiment(self, text: str) -> Tuple[float, str]:
        """Gets the sentiment score and label for a given text"""
        if self.sentiment_classifier:
            try:
                result = self.sentiment_classifier(text)[0]
                return result['score'], result['label']
            except Exception as e:
                logger.error(f"Error during sentiment analysis: {e}")
        return 0.0, "NEUTRAL"

    def is_complaint(self, email_body: str = None, email_subject: str = None) -> bool:
        """Checks if an email is a potential complaint based on sentiment and contextual analysis"""
        if not email_body or not email_subject:
            logger.warning("Missing email body or subject for complaint detection.")
            return False

        cleaned_body = clean_email(email_body)
        sentiment_score, sentiment_label = self.get_sentiment(cleaned_body)
        contextual_score = self.get_contextual_score(cleaned_body) if self.config.contextual_check.use_contextual_check else 0.0

        # Determine if complaint based on sentiment and contextual score
        if (sentiment_label == "NEGATIVE") and (sentiment_score >= self.config.sentiment_threshold or \
           contextual_score >= self.config.contextual_check.contextual_score_threshold):
            return True

        return False

    def process_email(self, message: Dict[str, Any], access_token: str, user_id: str) -> None:
        """Processes an email message for Sentiment Analysis and Complaint Detection"""
        subject: str = message.get("subject", "No Subject")
        sender: str = message.get("from", {}).get("emailAddress", {}).get("address", "No Sender")
        body_content: str = message["body"]["content"]
        message_id = message.get('id')

        header = f"X-Complaint-Processor: Processed-v1.0; ID={message_id};"
        message["body"]["content"] = header + message["body"]["content"]

        if any(re.match(value, sender) for value in self.config.exclusions.get('from', [])):
            logger.info(f"Excluded sender: {sender}")
            return
        if any(re.match(value, subject) for value in self.config.exclusions.get('subject', [])):
            logger.info(f"Excluded subject: {subject}")
            return

        if self.is_complaint(body_content, subject):
            logger.info(f"Complaint detected: Subject: {subject}, From: {sender}, Message ID: {message_id}")
            try:
                self.email_client.send_message_to_distribution_list(access_token, user_id, message_id)
                logger.info("Complaint forwarded to distribution list.")
                """
                if self.config.delete_original:
                    try:
                        delete_url = f"https://graph.microsoft.com/v1.0/users/{user_id}/messages/{message_id}"
                        delete_headers = {"Authorization": f"Bearer {access_token}"}
                        self.email_client._make_graph_api_request(delete_url, delete_headers, method="DELETE")
                        logger.info(f"Original message {message_id} deleted.")
                    except Exception as delete_error:
                        logger.exception(f"Error deleting original message {message_id}: {delete_error}")
                """
            except Exception as send_error:
                logger.exception(f"Error forwarding complaint: {send_error}")