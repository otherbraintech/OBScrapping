# Use official Playwright image which includes Python and browser dependencies
# This avoids manually installing heavy system dependencies
FROM mcr.microsoft.com/playwright/python:v1.40.0-jammy

WORKDIR /app

# Copy requirements first to cache dependencies
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Install specifically Chromium (the base image might have it, but this ensures it matches the lib version)
RUN playwright install chromium

# Copy application code
COPY main.py .

# Expose port
EXPOSE 80

# Run the application
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "80"]
