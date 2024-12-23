import os

#SENTIMENT_MODEL = os.environ.get("SENTIMENT_MODEL", "distilbert-base-uncased-finetuned-sst-2-english")
SENTIMENT_MODEL = os.environ.get("SENTIMENT_MODEL", "cardiffnlp/twitter-roberta-base-sentiment")
MONITORED_MAILBOXES = [
    "user1@yourdomain.com",
    "user2@yourdomain.com",
    "user3@yourdomain.com"  
    # Add more as needed
]
# Helper functions for delta token storage
DELTA_TOKEN_FILE = "delta_tokens.json"
COMPLAINT_THRESHOLD = .6
DISTRIBUTION_LIST_EMAIL = "complaints@your_domain.com"
CLIENT_ID = os.getenv("CLIENT_ID")  # Replace with your client ID or set as env variable
TENANT_ID = os.getenv("TENANT_ID")  # Replace with your tenant ID or set as env variable
REDIRECT_URI = "" # Must match the Redirect URI in your Azure AD app registration
AUTHORITY = f"https://login.microsoftonline.com/{TENANT_ID}"
SCOPES = ["User.Read", "Mail.Read"] # Add other scopes/permissions as needed
CLIENT_SECRET = os.getenv("CLIENT_SECRET")
EXCLUSIONS = {
    #'to': ['no-reply@your_domain.com', 'do-not-reply@your_domain.com'],
    'from': [r'*@*.gov', r'*@*.mil', r'*@*.us'],
    'subject': [r"Automatic Reply:.*"],
}
COMPLAINT_KEYWORDS_FILE = "complaint_keywords.txt"
SUBJECT_KEYWORDS_FILE = "subject_keywords.txt"
URGENCY_KEYWORDS_FILE = "urgency_keywords.txt"
NEGATION_KEYWORDS_FILE = "negation_keywords.txt"
# Weights (Adjust these as needed)
WEIGHTS = {
    "sentiment": 0.4,
    "body_keyword": 0.3,
    "subject_keyword": 0.2,
    "urgency": 0.1,
    "negation": -0.5
}
LOG_LEVEL = "INFO"
# 'process_main' is the main loops that checks complaint sentiment and forwards to distribution list for complaint handling
# 'feedback_loop' is the loop that checks for emails that contain our header and validate False Positives and False Negatives
# Use format like '30s', '5m', '1h'
SCHEDULING_INTERVALS = {
    "fp_feedback_loop": "2m",  # Check for False Positives (Returned Emails)
    "fn_feedback_loop": "2m",  # Check for False Negatives (Forwarded to Distribution List)
    "main_loop": "30s"
}

# Email filter for the feedback loop, etc.
EMAIL_FILTER = {
    #"from_domain": "example.com",  # Only process emails from this domain
    #"start_date": "2024-01-01",  # Only process emails after this date
    #"subject_contains": "Important", #Only process emails that contain "Important" in the subject
    "from_domain": "",
    "start_date": "",
    "subject_contains": "",
}

#API Max Retries / Delay
MAX_RETRIES = 3
RETRY_DELAY = 5  # Seconds

LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO")

CLIENT_ID = os.environ.get("CLIENT_ID")
AUTHORITY = os.environ.get("AUTHORITY")
CLIENT_SECRET = os.environ.get("CLIENT_SECRET")
SCOPES = os.environ.get("SCOPES")

COMPLAINT_KEYWORDS_FILE = "complaint_keywords.txt"
SUBJECT_KEYWORDS_FILE = "subject_keywords.txt"
URGENCY_KEYWORDS_FILE = "urgency_keywords.txt"
NEGATION_KEYWORDS_FILE = "negation_keywords.txt"

DISTRIBUTION_LIST_EMAIL = os.environ.get("DISTRIBUTION_LIST_EMAIL")
MONITORED_MAILBOXES = os.environ.get("MONITORED_MAILBOXES").split(",")
