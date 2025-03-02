# Use Python 3.11 slim image
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Set label for the application
LABEL maintainer="NexusAI Forge Team"
LABEL version="1.0.0"
LABEL description="Enterprise AI API service with key management, rate limiting, and usage tracking"

# Install system dependencies
RUN apt-get update && apt-get install -y \
    build-essential \
    libpq-dev \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for better caching
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir fastapi uvicorn sqlalchemy psycopg2-binary pydantic python-jose python-multipart passlib bcrypt httpx jinja2 pytest stripe python-dotenv

# Copy application code
COPY . .

# Apply bcrypt fix for passlib compatibility
RUN python fix_bcrypt.py

# Make sure the flows.db file exists and is writable
RUN touch flows.db && chmod 666 flows.db

# Create volume mount points
VOLUME ["/app/data"]

# Expose port
EXPOSE 8000

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV APP_NAME="NexusAI Forge"

# Run the application with uvicorn
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
