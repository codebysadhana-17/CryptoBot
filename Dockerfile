# Base image
FROM python:3.11-slim

# Set working directory inside container
WORKDIR /app

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=80

# Install dependencies
COPY requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt

# Copy application files
COPY . /app/

# Expose container port
EXPOSE 80

# Run Flask application using Gunicorn on Port 80
CMD ["gunicorn", "--bind", "0.0.0.0:80", "--workers", "1", "--threads", "4", "app:app"]
