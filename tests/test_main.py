import pytest
from unittest.mock import patch, MagicMock
from complaint_processor import ComplaintProcessor
from email_client import EmailClient
from utils import load_keywords_from_file
import config
import requests

@pytest.fixture
def mock_load_keywords():
    with patch("utils.load_keywords_from_file") as mock:
        yield mock

@pytest.mark.parametrize("body, subject, expected", [
    ("This is a problem.", "Urgent issue", True),
    ("This is not a problem.", "Everything is fine", False),
    ("There is no problem", "There is no issue", False),
    ("Urgent request", "", True),
    ("", "Urgent issue!", True),
])
def test_keyword_match(body, subject, expected, mock_load_keywords):
    mock_load_keywords.return_value = ["problem", "issue"]
    config.COMPLAINT_THRESHOLD = 1
    config.WEIGHTS = {"body_keyword": 1, "subject_keyword": 1, "urgency": 1, "negation": -0.5} #Set weights for proper testing
    complaint_processor = ComplaintProcessor(EmailClient())  # Need an EmailClient instance
    assert complaint_processor.keyword_match(body, subject) == expected

@patch("complaint_processor.classifier")
def test_is_complaint(mock_classifier):
    mock_classifier.return_value = [{"label": "NEGATIVE", "score": 0.9}]
    config.COMPLAINT_THRESHOLD = 0.8
    complaint_processor = ComplaintProcessor(EmailClient())
    assert complaint_processor.is_complaint("test body", "test subject") == True

    mock_classifier.return_value = [{"label": "POSITIVE", "score": 0.9}]
    assert complaint_processor.is_complaint("test body", "test subject") == False

    mock_classifier.side_effect = Exception("Sentiment analysis failed")
    assert complaint_processor.is_complaint("test body", "test subject") == False

@patch.object(EmailClient, "get_folder_id")
def test_get_folder_id(mock_get_folder_id):
    mock_get_folder_id.return_value = "123"
    access_token = "test_token"
    mailbox_address = "test@test.com"
    email_client = EmailClient()
    folder_id = email_client.get_folder_id(access_token, mailbox_address)
    assert folder_id == "123"

    mock_get_folder_id.return_value = None
    email_client = EmailClient()
    folder_id = email_client.get_folder_id(access_token, mailbox_address)
    assert folder_id is None

@patch.object(EmailClient, "get_access_token")
def test_get_access_token(mock_get_access_token):
    mock_get_access_token.return_value = "test_access_token"
    email_client = EmailClient()
    token = email_client.get_access_token()
    assert token == "test_access_token"

    mock_get_access_token.return_value = None
    token = email_client.get_access_token()
    assert token is None

@patch.object(EmailClient, "get_emails")
def test_get_emails(mock_get_emails):
    mock_get_emails.return_value = ([{"subject": "Test Email"}], "delta_link")
    access_token = "test_token"
    mailbox_address = "test@test.com"
    email_client = EmailClient()
    emails, delta_link = email_client.get_emails(access_token, mailbox_address)
    assert len(emails) == 1
    assert delta_link == "delta_link"

    mock_get_emails.return_value = ([], None)
    emails, delta_link = email_client.get_emails(access_token, mailbox_address)
    assert emails == []
    assert delta_link is None

@patch.object(EmailClient, "send_message_to_distribution_list")
def test_send_message_to_distribution_list(mock_send_message):
    access_token = "test_token"
    user_id = "test@test.com"
    message_id = "12345"
    email_client = EmailClient()
    email_client.send_message_to_distribution_list(access_token, user_id, message_id)
    mock_send_message.assert_called_once_with(access_token, user_id, message_id)
