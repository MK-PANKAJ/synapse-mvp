import os
import google.generativeai as genai
import vertexai
from vertexai.generative_models import GenerativeModel
from google.cloud import firestore
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from youtube_transcript_api import YouTubeTranscriptApi
from typing import List, Optional, Dict
from python_dotenv import load_dotenv

load_dotenv()

# --- CONFIGURATION ---
PROJECT_ID = os.getenv("GCP_PROJECT", "your-project-id")
LOCATION = os.getenv("GOOGLE_CLOUD_LOCATION", "us-central1")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY") # API Key for Local Mode

# Global Services
model = None
db = None
mock_db: Dict[str, dict] = {} # In-memory DB for local mode

# Initialize AI Service
if GEMINI_API_KEY:
    print("Using Local Mode with Gemini API Key")
    genai.configure(api_key=GEMINI_API_KEY)
    model = genai.GenerativeModel('gemini-1.5-pro')
else:
    print("Attempting Cloud Mode with Vertex AI")
    try:
        vertexai.init(project=PROJECT_ID, location=LOCATION)
        model = GenerativeModel("gemini-1.5-pro-001")
    except Exception as e:
        print(f"Warning: Vertex AI init failed: {e}")

# Initialize Database Service
try:
    db = firestore.Client(project=PROJECT_ID)
    print("Firestore Connected")
except Exception as e:
    print(f"Warning: Firestore init failed: {e}. Switching to Mock DB (Local Mode).")
    db = None

app = FastAPI(title="Synapse API", version="1.0-Local")

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
        if "ADHD" in profile:
            return "Format: High-energy, emoji-bullet points. Max 3 bullets."
        if "Dyslexia" in profile:
            return "Format: Simple syntax. Use visual metaphors."
        return "Format: Clear, academic summary."

    @staticmethod
    def generate_content(transcript: str, profile: str):
        if not model:
            return "{\"summary\": \"Error: AI not connected. Check API Key.\", \"bingo_terms\": []}"
            
        system_instruction = CognitiveService.get_prompt_logic(profile)
        prompt = f"""
        ROLE: Expert Educational Neuro-adapter.
        INSTRUCTION: {system_instruction}
        TASK: Analyze this transcript.
        1. Create a structured learning card summary.
        2. Extract exactly 9 "Bingo Keywords" (single words) central to the topic.
        
        TRANSCRIPT: {transcript[:10000]}...
        
        OUTPUT FORMAT (Strict JSON):
        {{
            "summary": "markdown_text_here",
            "bingo_terms": ["term1", "term2", ...]
        }}
        """
        try:
            response = model.generate_content(prompt)
            return response.text
        except Exception as e:
            return f"{{\"summary\": \"AI Error: {str(e)}\", \"bingo_terms\": []}}"

    @staticmethod
    def generate_podcast_script(transcript: str):
        if not model:
            return "Error: AI not connected."
            
        prompt = "Convert this transcript into a podcast script between Dr. V and Max:\n" + transcript[:10000]
        try:
            response = model.generate_content(prompt)
            return response.text
        except Exception as e:
            return f"AI Error: {str(e)}"

class DatabaseService:
    @staticmethod
    def save_lecture(user_id, video_id, summary_data, transcript_snippet):
        data = {
            "video_id": video_id,
            "status": "processed",
            "summary_data": summary_data,
            "context_snippet": transcript_snippet, 
            "timestamp": "NOW"
        }
        
        if db:
            doc_ref = db.collection("users").document(user_id).collection("lectures").document(video_id)
            doc_ref.set(data)
            return doc_ref.id
        else:
            # Local Mock DB
            mock_key = f"{user_id}_{video_id}"
            mock_db[mock_key] = data
            print(f"[Local DB] Saved lecture {video_id} to memory.")
            return "mock-id"

    @staticmethod
    def get_context(user_id, video_id):
        if db:
            doc = db.collection("users").document(user_id).collection("lectures").document(video_id).get()
            return doc.to_dict().get("context_snippet", "") if doc.exists else ""
        else:
            mock_key = f"{user_id}_{video_id}"
            return mock_db.get(mock_key, {}).get("context_snippet", "")

# --- API ENDPOINTS ---
@app.post("/api/v1/ingest")
async def ingest_lecture(payload: VideoIngest):
    try:
        video_id = payload.video_url.split("v=")[1].split("&")[0] if "v=" in payload.video_url else "mock_vid"
        
        try:
            transcript_list = YouTubeTranscriptApi.get_transcript(video_id)
            full_text = " ".join([t['text'] for t in transcript_list])
        except:
             # Fallback for testing without valid video
             full_text = "This is a mock transcript about Mitochondria." 
        
        ai_response = CognitiveService.generate_content(full_text, payload.user_profile)
        DatabaseService.save_lecture(payload.user_id, video_id, ai_response, full_text[:10000])
        
        return {
            "status": "success", 
            "lecture_id": video_id, 
            "content": ai_response,
            "transcript_context": full_text[:5000]
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/v1/generate-podcast")
async def generate_podcast_endpoint(payload: PodcastRequest):
    return {"status": "success", "script": CognitiveService.generate_podcast_script(payload.transcript_text)}

@app.post("/api/v1/ask-doubt")
async def solve_doubt(payload: DoubtQuery):
    context = DatabaseService.get_context(payload.user_id, payload.lecture_id)
    if not context: context = "Context not found."
    
    chat_prompt = f"Context: {context}\nQuestion: {payload.question}\nAnswer in 2 sentences."
    
    if model:
        response = model.generate_content(chat_prompt)
        return {"answer": response.text}
    else:
        return {"answer": "AI not connected."}


