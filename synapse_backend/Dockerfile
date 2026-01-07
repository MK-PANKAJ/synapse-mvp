FROM python:3.9-slim

WORKDIR /app

COPY requirements.txt .
RUN apt-get update && apt-get install -y ffmpeg && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Expose the port (good practice for Cloud Run)
EXPOSE 8080

# Use standard shell form which allows $PORT expansion by default
CMD exec uvicorn main:app --host 0.0.0.0 --port ${PORT:-8080}
