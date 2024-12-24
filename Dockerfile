# buid image
FROM python:3.11-slim AS build-env
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .

# runtime image
FROM python:3.11-slim
WORKDIR /app
COPY --from=build-env /app /app
COPY --from=build-env /app/token_cache.bin /app/token_cache.bin
ENV LOG_LEVEL="INFO"
ENV CONFIG_FILE="config.json"
CMD ["python", "main.py"]