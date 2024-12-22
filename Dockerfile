# Use a Python base image
FROM python:3.9-slim-buster

# Set working directory
WORKDIR /app

# Copy requirements file if you have one
COPY requirements.txt .
# Install dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy your application code
COPY . .

# Set environment variables
ENV CLIENT_ID=your_client_id
ENV AUTHORITY=your_authority
ENV CLIENT_SECRET=your_client_secret
ENV SCOPES=your_scopes
ENV DISTRIBUTION_LIST_EMAIL=your_distribution_list_email
ENV MONITORED_MAILBOXES=mailbox1@example.com,mailbox2@example.com


# Set the entry point for the container
CMD ["python", "main.py"]