# Synapse MVP - Production Setup Guide

## 🚀 Overview
Synapse is an AI-powered Neuro-adaptive Learning Platform that transforms standard educational content (videos/lectures) into personalized learning experiences.

### Key Features
*   **Neuro-Adaptation**: Tailors content for ADHD, Dyslexia, and Visual learners.
*   **Multimodal Ingestion**: Upload videos or paste YouTube links.
*   **AI Podcast Generator**: Converts lectures into engaging, viral-style audio podcasts.
*   **Visual Knowledge Graphs**: Automatically generates Mermaid.js diagrams to visualize concepts.
*   **Hybrid Architecture**: Runs locally (Zero Cost) or scales on Google Cloud (Production).

---

## 1. Prerequisites
*   **Git**: [Download for Windows](https://git-scm.com/download/win).
*   **Flutter SDK**: [Download Guide](https://docs.flutter.dev/get-started/install/windows).
*   **Google Cloud SDK**: [Download](https://cloud.google.com/sdk/docs/install).
*   (Optional) **Docker Desktop**: For container testing.

---

## 2. Backend Setup (Hybrid API)

### Mode A: Local Prototype (Zero Cost)
Use this for testing without a cloud bill.
1.  **Get API Key**: Get a free key from [Google AI Studio](https://aistudio.google.com/).
2.  **Configure**:
    ```bash
    # Windows (Powershell)
    $env:GEMINI_API_KEY="your_api_key_here"
    ```
3.  **Run**:
    ```bash
    cd synapse_backend
    pip install -r requirements.txt
    uvicorn main:app --reload
    ```
    *Note: In this mode, the database is in-memory and resets on restart.*

### Mode B: Cloud Production (Google Cloud Run)
Use this for the final demo/hackathon submission.
1.  **Setup Script**:
    ```bash
    ./setup_new_project.sh <YOUR_PROJECT_ID>
    ```
    *This enables APIs (Vertex AI, Firestore), creates the .env file, and deploys to Cloud Run.*

2.  **Manual Deployment**:
    ```bash
    gcloud run deploy synapse-backend --source synapse_backend --allow-unauthenticated
    ```

---

## 3. Frontend Setup (Flutter App)

1.  **Install Dependencies**:
    ```bash
    cd synapse_frontend
    flutter pub get
    ```

2.  **Configure Backend**:
    *   **Option 1 (Build Argument)**:
        ```bash
        flutter run --dart-define=BACKEND_URL="https://your-cloud-run-url.run.app"
        ```
    *   **Option 2 (Default)**:
        If you don't provide a URL, it defaults to the production URL or localhost. You can edit `lib/main.dart` to change the default fallback.

3.  **Run**:
    ```bash
    flutter run
    ```

---

## 🔄 Synapse Workflow

### 1. User Onboarding
*   On first launch, the app generates a unique **Anonymous User ID** (UUID) stored on the device.
*   No login required (frictionless entry).

### 2. Ingestion (The "Synapse")
*   **Input**: User pastes a YouTube Link or uploads an MP4 file.
*   **Profile Selection**: User selects their learning profile (e.g., "ADHD", "Dyslexia", "Hinglish").
*   **Processing**:
    *   **Backend**: Downloads audio (if YouTube) or streams upload (if file).
    *   **AI Analysis**: Uses **Gemini 1.5 Flash** (via Vertex AI or Studio API) to analyze the content.
    *   **Context Caching**: Large videos use Cloud Storage URI context to prevent re-uploading bytes.

### 3. Neuro-Adaptation Output
The Dashboard presents the content in 4 transformed modalities:
*   **Summary Tab**: Markdown summary tailored to the profile (e.g., bullet points for ADHD).
*   **Focus Points**: 5-7 punchy, "Bingo-style" key takeaways.
*   **Visual Tab**: A **Knowledge Graph** (Mermaid.js) helping visual learners connect concepts.
*   **Podcast Tab**: An auto-generated 2-minute "Study Podcast" script (Viral/Hinglish style).

### 4. Interactive Learning
*   **Video Player**: Watch the original content directly in the app.
*   **Doubt Resolver**: Ask questions ("Explain this like I'm 5"). The AI uses the video context to answer.

---

## 5. Deployment Guide (Web)

To host the Synapse Frontend as a website:

1.  **Build**:
    ```bash
    cd synapse_frontend
    # Replace with your actual backend URL
    flutter build web --release --dart-define=BACKEND_URL="https://synapse-backend-xyz.run.app"
    ```

2.  **Deploy to GitHub Pages**:
    *   Push your code to GitHub.
    *   The included workflow (`.github/workflows/deploy.yml`) will automatically build and deploy the site to `Run on GitHub Pages`.

---

## 🛠️ Architecture

*   **Frontend**: Flutter (Mobile/Web/Desktop)
*   **Backend**: FastAPI (Python)
*   **AI Engine**: Gemini 1.5 Flash (via Vertex AI or Google AI Studio)
*   **Database**: Firestore (NoSQL)
*   **Storage**: Google Cloud Storage (Video/Audio Buffer)
