FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application files
COPY leader.py .
COPY follower.py .
COPY run_followers.py .

# Default command runs leader
CMD ["python", "leader.py"]

