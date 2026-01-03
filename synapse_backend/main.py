import os
import vertexai
from vertexai.generative_models import GenerativeModel, Part
from google.cloud import firestore, storage
from fastapi import FastAPI, HTTPException, UploadFile, File
from pydantic import BaseModel
from youtube_transcript_api import YouTubeTranscriptApi
import yt_dlp
from typing import List, Optional, Dict
from dotenv import load_dotenv
from fastapi.middleware.cors import CORSMiddleware

load_dotenv()

# --- CLOUD CONFIGURATION ---
# Default to current environment if variables not set
PROJECT_ID = os.getenv("GCP_PROJECT", "synapse-483211") 
LOCATION = os.getenv("GOOGLE_CLOUD_LOCATION", "us-central1")
BUCKET_NAME = f"{PROJECT_ID}-uploads" # Storage Bucket Name

print(f"Starting Synapse Backend in CLOUD MODE.")
print(f"Project: {PROJECT_ID}, Location: {LOCATION}")

# --- INITIALIZE GOOGLE CLOUD SERVICES ---
try:
    # 1. Vertex AI
    vertexai.init(project=PROJECT_ID, location=LOCATION)
    model = GenerativeModel("gemini-2.5-flash")
    print("SUCCESS: Vertex AI Initialized.")

    # 2. Firestore
    db = firestore.Client(project=PROJECT_ID)
    print("SUCCESS: Firestore Initialized.")

    # 3. Cloud Storage
    storage_client = storage.Client(project=PROJECT_ID)
    print("SUCCESS: Storage Initialized.")
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
2. Extract 5-7 "Focus Points" (Micro-summaries: punchy, emoji-bullet points, max 10 words each) to help the student maintain attention.

OUTPUT JSON FORMAT:
{{
    "summary": "...markdown content...",
    "focus_points": ["⚡ Point 1", "🧠 Point 2", ...],
    "mermaid_diagram": "graph TD; A[Concept] --> B[Result]; ..." (Optional, send blank string if not applicable)
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
    user_id: str
    question: str
    user_profile: str = "General" # Default for backward compatibility

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
            return "Format: Simple syntax. Visual metaphors. No walls of text."
        if "Visual" in profile:
            return "Format: Highly visual. Create a Mermaid.js flowchart describing the process."
        return "Format: Clear, academic summary."

    @staticmethod
    def generate_content(transcript: str, profile: str, video_uri: Optional[str] = None):
        if not model:
            raise HTTPException(status_code=500, detail="Vertex AI is not connected. Check Server Logs.")
            
        profile_instruction = CognitiveService.get_prompt_logic(profile)
        system_prompt = SYSTEM_PROMPT_TEMPLATE.format(profile_instruction=profile_instruction)
        
        try:
            inputs = [system_prompt]
            if video_uri:
                # MULTIMODAL MODE (Video + Text Prompt)
                print(f"DEBUG: Processing Video from {video_uri}")
                mime_type = "audio/mp3" if video_uri.endswith(".mp3") else "video/mp4"
                video_part = Part.from_uri(uri=video_uri, mime_type=mime_type)
                inputs.append(video_part)
                inputs.append("Analyze this content.")
            else:
                # TEXT MODE (Transcript Only)
                inputs.append(f"\n\nTRANSCRIPT:\n{transcript[:25000]}...") # Increased limit for text

            response = model.generate_content(inputs)
            return response.text
        except Exception as e:
            print(f"Vertex Generation Error: {e}")
            return f"{{\"summary\": \"AI Error: {str(e)}\", \"focus_points\": []}}"

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
@app.post("/api/v1/upload")
async def upload_video(file: UploadFile = File(...)):
    if not storage_client:
        raise HTTPException(status_code=500, detail="Storage not initialized.")
        
    try:
        bucket = storage_client.bucket(BUCKET_NAME)
        blob = bucket.blob(f"uploads/{file.filename}")
        blob.upload_from_file(file.file, content_type=file.content_type)
        
        return {"status": "success", "video_uri": f"gs://{BUCKET_NAME}/uploads/{file.filename}"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Upload Failed: {str(e)}")

@app.post("/api/v1/ingest")
async def ingest_lecture(payload: VideoIngest):
    # Handle GCS Video (Direct Upload)
    if payload.video_url.startswith("gs://"):
        video_id = payload.video_url.split("/")[-1] # filename as ID
        full_text = "Video Content (Processed via Multimodal AI)"
        
        ai_response = CognitiveService.generate_content("", payload.user_profile, video_uri=payload.video_url)
        
    # Handle YouTube Video
    else:
        video_id = payload.video_url.split("v=")[1].split("&")[0] if "v=" in payload.video_url else "mock_vid"
        
        try:
            transcript_list = YouTubeTranscriptApi.get_transcript(video_id)
            full_text = " ".join([t['text'] for t in transcript_list])
            ai_response = CognitiveService.generate_content(full_text, payload.user_profile)
        except Exception as e:
            print(f"Transcript Failed ({e}). Attempting Audio Fallback...")
            # FALLBACK: Download Audio -> GCS -> Gemini
            try:
                ydl_opts = {
                    'format': 'bestaudio/best',
                    'outtmpl': f'/tmp/{video_id}.%(ext)s',
                    'postprocessors': [{'key': 'FFmpegExtractAudio','preferredcodec': 'mp3',}],
                    'quiet': True
                }
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    ydl.download([payload.video_url])
                
                # Upload to GCS
                bucket = storage_client.bucket(BUCKET_NAME)
                blob = bucket.blob(f"audio_cache/{video_id}.mp3")
                blob.upload_from_filename(f"/tmp/{video_id}.mp3")
                
                audio_uri = f"gs://{BUCKET_NAME}/audio_cache/{video_id}.mp3"
                full_text = "Audio Content (Processed via Multimodal AI)"
                ai_response = CognitiveService.generate_content("", payload.user_profile, video_uri=audio_uri)
                
            except Exception as dl_error: 
                print(f"Audio Fallback Failed: {dl_error}")
                raise HTTPException(status_code=400, detail="Could not retrieve transcript AND Audio Download failed. Video is likely private or age-restricted.")

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
    
    # Cognitive Translation Logic
    profile_instruction = CognitiveService.get_prompt_logic(payload.user_profile)
    
    chat_prompt = f"""
    ROLE: Expert Private Tutor.
    STYLE: {profile_instruction}
    
    CONTEXT: {context[:5000]}
    
    STUDENT QUESTION: {payload.question}
    ANSWER:
    """
    
    if model:
        try:
            response = model.generate_content(chat_prompt)
            return {"answer": response.text}
        except Exception as e:
            return {"answer": f"AI Error: {str(e)}"}
    else:
        return {"answer": "AI not connected."}


