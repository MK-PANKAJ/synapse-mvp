import os
import vertexai
from vertexai.generative_models import GenerativeModel
from google.cloud import firestore
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from youtube_transcript_api import YouTubeTranscriptApi
from typing import List, Optional, Dict
from dotenv import load_dotenv
from fastapi.middleware.cors import CORSMiddleware

load_dotenv()

# --- CLOUD CONFIGURATION ---
# Default to current environment if variables not set
PROJECT_ID = os.getenv("GCP_PROJECT", "synapse-483211") 
LOCATION = os.getenv("GOOGLE_CLOUD_LOCATION", "us-central1")

print(f"Starting Synapse Backend in CLOUD MODE.")
print(f"Project: {PROJECT_ID}, Location: {LOCATION}")

# --- INITIALIZE GOOGLE CLOUD SERVICES ---
try:
    # 1. Vertex AI
    vertexai.init(project=PROJECT_ID, location=LOCATION)
    model = GenerativeModel("gemini-1.5-flash-001")
    print("SUCCESS: Vertex AI Initialized.")

    # 2. Firestore
    db = firestore.Client(project=PROJECT_ID)
    print("SUCCESS: Firestore Initialized.")
except Exception as e:
    print(f"CRITICAL ERROR - CLOUD INIT FAILED: {e}")
    # We do NOT crash here so logs can be read, but app will be broken.
    model = None
    db = None

app = FastAPI(title="Synapse API (Cloud Only)", version="2.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- AI PROMPTS ---
SYSTEM_PROMPT_TEMPLATE = """
You are an Expert Educational Neuro-adapter.
BASE INSTRUCTION: Make it extremely simple (ELIF5). Use analogies.
PROFILE ADAPTATION: {profile_instruction}

TASK: Analyze the transcript and extract structured learning data.
1. Create a "Learning Card Summary" (Markdown).
2. Extract exactly 9 "Bingo Keywords".

OUTPUT JSON FORMAT:
{{
    "summary": "...markdown content...",
    "bingo_terms": ["term1", "term2", ...]
}}
"""

PODCAST_PROMPT_TEMPLATE = """
You are 'Synapse FM', a viral study podcast.
Convert the transcript into a fun, Hinglish (Hindi+English) conversation.

CHARACTERS:
1. **Dr. V** (The Expert): Calm, academic, speaks mostly English.
2. **Max** (The Student): High energy, curious, uses Gen-Z Hinglish slang (e.g., "Arre sir", "Op bhai", "Matlab?").

RULES:
- Keep it under 2 minutes.
- Max asks the "dumb" questions everyone is thinking.
- Use analogies.
- NO Sound Effects.
"""

# --- DATA MODELS ---
class VideoIngest(BaseModel):
    user_id: str
    video_url: str
    user_profile: str

class DoubtQuery(BaseModel):
    lecture_id: str
    user_id: str
    question: str

class PodcastRequest(BaseModel):
    transcript_text: str

# --- SERVICE LAYER ---
class CognitiveService:
    @staticmethod
    def get_prompt_logic(profile: str):
        if "Hinglish" in profile:
            return "Explain in mixed Hindi-English for an Indian Gen-Z student."
        if "ADHD" in profile:
            return "Format: High-energy, emoji-bullet points. Short sentences."
        if "Dyslexia" in profile:
            return "Format: Simple syntax. Use visual metaphors. No walls of text."
        return "Format: Clear, academic summary."

    @staticmethod
    def generate_content(transcript: str, profile: str):
        if not model:
            raise HTTPException(status_code=500, detail="Vertex AI is not connected. Check Server Logs.")
            
        profile_instruction = CognitiveService.get_prompt_logic(profile)
        prompt = SYSTEM_PROMPT_TEMPLATE.format(profile_instruction=profile_instruction)
        prompt += f"\n\nTRANSCRIPT:\n{transcript[:10000]}..."
        
        try:
            response = model.generate_content(prompt)
            return response.text
        except Exception as e:
            print(f"Vertex Generation Error: {e}")
            raise HTTPException(status_code=500, detail=f"Vertex AI Error: {str(e)}")

    @staticmethod
    def generate_podcast_script(transcript: str):
        if not model:
            raise HTTPException(status_code=500, detail="Vertex AI is not connected.")
            
        prompt = PODCAST_PROMPT_TEMPLATE + f"\n\nTRANSCRIPT:\n{transcript[:10000]}"
        
        try:
            response = model.generate_content(prompt)
            return response.text
        except Exception as e:
             raise HTTPException(status_code=500, detail=f"Vertex AI Error: {str(e)}")

class DatabaseService:
    @staticmethod
    def save_lecture(user_id, video_id, summary_data, transcript_snippet):
        if not db:
             print("Firestore not connected. Skipping save.")
             return "error-no-db"

        data = {
            "video_id": video_id,
            "status": "processed",
            "summary_data": summary_data,
            "context_snippet": transcript_snippet, 
            "timestamp": firestore.SERVER_TIMESTAMP
        }
        
        doc_ref = db.collection("users").document(user_id).collection("lectures").document(video_id)
        doc_ref.set(data)
        return doc_ref.id

    @staticmethod
    def get_context(user_id, video_id):
        if not db: return ""
        doc = db.collection("users").document(user_id).collection("lectures").document(video_id).get()
        return doc.to_dict().get("context_snippet", "") if doc.exists else ""

# --- API ENDPOINTS ---
@app.post("/api/v1/ingest")
async def ingest_lecture(payload: VideoIngest):
    video_id = payload.video_url.split("v=")[1].split("&")[0] if "v=" in payload.video_url else "mock_vid"
    
    try:
        transcript_list = YouTubeTranscriptApi.get_transcript(video_id)
        full_text = " ".join([t['text'] for t in transcript_list])
    except:
            full_text = "This is a mock transcript about Mitochondria because YouTube failed." 
    
    ai_response = CognitiveService.generate_content(full_text, payload.user_profile)
    DatabaseService.save_lecture(payload.user_id, video_id, ai_response, full_text[:10000])
    
    return {
        "status": "success", 
        "lecture_id": video_id, 
        "content": ai_response,
        "transcript_context": full_text[:5000]
    }

@app.post("/api/v1/generate-podcast")
async def generate_podcast_endpoint(payload: PodcastRequest):
    return {"status": "success", "script": CognitiveService.generate_podcast_script(payload.transcript_text)}

@app.post("/api/v1/ask-doubt")
async def solve_doubt(payload: DoubtQuery):
    context = DatabaseService.get_context(payload.user_id, payload.lecture_id)
    chat_prompt = f"Context: {context}\nQuestion: {payload.question}\nAnswer in 2 sentences."
    
    if model:
        response = model.generate_content(chat_prompt)
        return {"answer": response.text}
    else:
        return {"answer": "AI not connected."}


