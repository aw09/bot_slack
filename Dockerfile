# Dockerfile for deploying the Slack Thread Analyzer Bot on Railway
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Install Python dependencies
COPY requirements.txt ./
RUN pip install --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

# Copy the application code
COPY . .

# Railway injects PORT; default to 3000 for local runs
ENV PORT=3000

# Use a single gunicorn worker; background thread pool handles async work
CMD ["sh", "-c", "gunicorn -w 1 -b 0.0.0.0:${PORT:-3000} apps:app"]
