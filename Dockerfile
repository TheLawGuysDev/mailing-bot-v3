# Use a slim Python base image
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Prevent Python from writing .pyc files and buffer logs
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Install system dependencies (needed for some libs like uvicorn, jose, passlib)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
  && rm -rf /var/lib/apt/lists/*

# Copy requirements and install dependencies
COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the app code
COPY . .

# Cloud Run will inject $PORT; default to 8080 for local docker run
ENV PORT=8080

# Start the FastAPI app with uvicorn
# main:app -> file `main.py`, variable `app`
CMD ["bash", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT}"]