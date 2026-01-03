# 1. Set the new project as active
gcloud config set project synapse-483211

# 2. Enable necessary APIs (Billing must be linked first!)
gcloud services enable run.googleapis.com \
    aiplatform.googleapis.com \
    firestore.googleapis.com \
    cloudbuild.googleapis.com

# 3. Create the .env file for the backend
echo "GCP_PROJECT=synapse-483211" > synapse_backend/.env
echo "GOOGLE_CLOUD_LOCATION=us-central1" >> synapse_backend/.env

# 4. Deploy to Cloud Run
cd synapse_backend
gcloud run deploy synapse-backend --source . --allow-unauthenticated
