import re
from typing import Dict, Any, List
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.exceptions import NotFittedError
from transformers import pipeline
from .email_client import EmailClient
from .utils import clean_email, load_keywords_from_file
from .config_loader import Config
from loguru import logger
import time

class ComplaintProcessor:
    def __init__(self, email_client: EmailClient, config: Config):
        self.email_client = email_client
        self.config = config
        self.classifier = None
        self.vectorizer = TfidfVectorizer(
            vocabulary=load_keywords_from_file(self.config.complaint_keywords_file),
            stop_words='english'
        )
        self.reload_keywords()
        self.reload_sentiment_pipeline()

    def reload_sentiment_pipeline(self):
        """Attempts to initialize sentiment analysis pipeline with retries"""
        max_retries = self.config.sentiment_pipeline_max_retries
        retry_delay = self.config.sentiment_pipeline_retry_delay
        for attempt in range(max_retries):
            try:
                self.classifier = pipeline("sentiment-analysis", model=self.config.sentiment_model)
                logger.info(f"Initialized sentiment analysis pipeline with model: {self.config.sentiment_model}")
                return  # Success, exit the function
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
        # Update the vocabulary of the vectorizer
        self.vectorizer.vocabulary_ = self.complaint_keywords

    def keyword_match_tfidf(self, cleaned_body: str, cleaned_subject: str) -> bool:
        """Determines if an email is a complaint based on TF-IDF keyword matching"""
        try:
            # Check if vectorizer has vocabulary
            if not self.vectorizer.vocabulary_:
                logger.warning("Vectorizer has no vocabulary. Reloading keywords.")
                self.reload_keywords()

            body_tfidf = self.vectorizer.transform([cleaned_body])
            subject_tfidf = self.vectorizer.transform([cleaned_subject])
        except NotFittedError:
            logger.warning("Vectorizer not fitted. Fitting with complaint keywords.")
            self.vectorizer.fit(load_keywords_from_file(self.config.complaint_keywords_file))
            body_tfidf = self.vectorizer.transform([cleaned_body])
            subject_tfidf = self.vectorizer.transform([cleaned_subject])
        except ValueError:
            logger.error("Vectorizer error: empty vocabulary. Check complaint_keywords_file.")
            return False

        body_score = body_tfidf.max()
        subject_score = subject_tfidf.max()

        # Combine scores (you can adjust the weighting here)
        combined_score = (
            body_score * self.config.weights.body_keyword
            + subject_score * self.config.weights.subject_keyword
        )

        return combined_score >= self.config.keyword_threshold

    def is_complaint(self, email_body: str = None, email_subject: str = None) -> bool:
        """Checks if an email is a potential complaint based on keywords and sentiment"""
        if not email_body or not email_subject:
            logger.warning("Missing email body or subject for complaint detection.")
            return False

        cleaned_body = clean_email(email_body)
        cleaned_subject = clean_email(email_subject)

        # Basic Contextual Check: Look for complaint keywords near negative sentiment words
        contextual_complaint = False
        if self.classifier:
            try:
                sentiment_result = self.classifier(cleaned_body)[0]
                sentiment_label: str = sentiment_result['label']
                sentiment_score: float = sentiment_result['score']

                if sentiment_label == "NEGATIVE":
                    for keyword in self.complaint_keywords:
                        if re.search(r"\b" + re.escape(keyword) + r"\b", cleaned_body, re.IGNORECASE):
                            # Check for proximity
                            keyword_index = cleaned_body.lower().find(keyword.lower())
                            negation_proximity = self.config.contextual_check.negation_proximity
                            negative_proximity = self.config.contextual_check.negative_proximity
                            negative_words = self.config.contextual_check.negative_words

                            if any(-negation_proximity < cleaned_body.lower().find(neg_word.lower()) - keyword_index < negation_proximity for neg_word in self.negation_keywords):
                                contextual_complaint = False
                                break  # Found negation, don't consider it a complaint
                            elif any(-negative_proximity < cleaned_body.lower().find(neg_word.lower()) - keyword_index < negative_proximity for neg_word in negative_words):
                                contextual_complaint = True
                                break  # Found negative word nearby, consider it a contextual complaint

            except Exception as e:
                logger.error(f"Error during sentiment analysis: {e}")
                if self.config.fallback:
                    return self.keyword_match_tfidf(cleaned_body, cleaned_subject)
                return False

            # Consider sentiment in the decision
            if sentiment_label == "NEGATIVE" and sentiment_score >= self.config.sentiment_threshold:
                return True

        # Use TF-IDF if sentiment is not negative or if contextual_complaint is True
        if self.config.fallback or contextual_complaint:
            return self.keyword_match_tfidf(cleaned_body, cleaned_subject)

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
            except Exception as send_error:
                logger.exception(f"Error forwarding complaint: {send_error}")