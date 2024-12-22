# Complaint Processor

Test project provides a Python application for processing complaint emails received from a designated mailbox. It aims to identify and forward genuine complaints to a distribution list for further action.

**Features:**

*   Connects to Microsoft Graph API to retrieve emails from a monitored mailbox.
*   Analyzes email content based on pre-defined keywords (complaint keywords, urgency keywords, negation keywords).
*   Identifies potential complaints based on keyword presence and sentiment analysis (optional, depending on implementation).
*   Forwards identified complaints to a designated distribution list email address.

