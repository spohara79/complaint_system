# Build Stage
FROM python:3.9-slim-buster AS builder

WORKDIR /app

COPY requirements.txt .

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Runtime Stage
FROM python:3.9-slim-buster

WORKDIR /app

# Copy only the necessary artifacts from the builder stage
COPY --from=builder /app/main.py /app/
COPY --from=builder /app/email_client.py /app/
COPY --from=builder /app/complaint_processor.py /app/
COPY --from=builder /app/utils.py /app/
COPY --from=builder /app/config.py /app/
COPY --from=builder /app/complaint_keywords.txt /app/
COPY --from=builder /app/subject_keywords.txt /app/
COPY --from=builder /app/urgency_keywords.txt /app/
COPY --from=builder /app/negation_keywords.txt /app/
RUN touch /app/delta_tokens.json

# Copy the installed site-packages from the builder stage
COPY --from=builder /usr/local/lib/python3.9/site-packages /usr/local/lib/python3.9/site-packages

# Set environment variables
ENV CLIENT_ID=your_client_id
ENV AUTHORITY=your_authority
ENV CLIENT_SECRET=your_client_secret
ENV SCOPES=your_scopes
ENV DISTRIBUTION_LIST_EMAIL=your_distribution_list_email
ENV MONITORED_MAILBOXES=mailbox1@example.com,mailbox2@example.com

# Set the entry point
CMD ["python", "main.py"]