# 1. Set the new project as active
# Check if argument is provided
if [ -z "$1" ]; then
    echo "Usage: ./setup_new_project.sh <PROJECT_ID>"
    echo "Please provide your Google Cloud Project ID."
    read -p "Project ID: " PROJECT_ID
else
    PROJECT_ID=$1
fi

if [ -z "$PROJECT_ID" ]; then
    echo "Error: Project ID is required."
    exit 1
fi

echo "Setting up Synapse for Project: $PROJECT_ID"
gcloud config set project $PROJECT_ID

# 2. Enable necessary APIs (Billing must be linked first!)
gcloud services enable run.googleapis.com \
    aiplatform.googleapis.com \
    firestore.googleapis.com \
    cloudbuild.googleapis.com

# 3. Create the .env file for the backend
echo "GCP_PROJECT=$PROJECT_ID" > synapse_backend/.env
echo "GOOGLE_CLOUD_LOCATION=us-central1" >> synapse_backend/.env

# 4. Deploy to Cloud Run
cd synapse_backend
gcloud run deploy synapse-backend --source . --allow-unauthenticated
