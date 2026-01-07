#!/bin/bash

# Synapse MVP - Backend Updater Script
# Usage: ./update_backend.sh

echo "============================================="
echo "   Synapse MVP - Backend Updater"
echo "============================================="

# 1. Confirm Project ID
PROJECT_ID=$(gcloud config get-value project)
echo "Target Project: $PROJECT_ID"
echo "Target Region: us-central1 (default)"

if [ -z "$PROJECT_ID" ]; then
    echo "Error: No active Google Cloud project found."
    echo "Run: gcloud config set project <YOUR_PROJECT_ID>"
    exit 1
fi

# 2. Deploy to Cloud Run
echo ""
echo "Deploying to Cloud Run..."
echo "---------------------------------------------"
gcloud run deploy synapse-backend \
    --source synapse_backend \
    --region us-central1 \
    --allow-unauthenticated

if [ $? -eq 0 ]; then
    echo "============================================="
    echo "   Deployment Complete!"
    echo "============================================="
else
    echo "============================================="
    echo "   Deployment FAILED"
    echo "============================================="
    exit 1
fi
