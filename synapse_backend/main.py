import os
import mimetypes
import time
import random
import vertexai
try:
    from vertexai.generative_models import GenerativeModel, Part, GenerationConfig, Content
except ImportError:
    try:
        from vertexai.preview.generative_models import GenerativeModel, Part, GenerationConfig, Content
    except ImportError:
        print("WARNING: Could not import Vertex AI GenerativeModel. AI features will be disabled.")
        GenerativeModel = None
        Part = None
        GenerationConfig = None
        Content = None
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
PROJECT_ID = os.getenv("GCP_PROJECT")
LOCATION = os.getenv("GOOGLE_CLOUD_LOCATION", "us-central1")
BUCKET_NAME = f"{PROJECT_ID}-uploads" if PROJECT_ID else "local-uploads" # Storage Bucket Name
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

if not PROJECT_ID:
    print("WARNING: GCP_PROJECT not set. Ensure it is set in .env or Cloud Run environment.")

print(f"Starting Synapse Backend.")
print(f"Project: {PROJECT_ID}, Location: {LOCATION}")

# --- INITIALIZE AI SERVICES ---
try:
    # 1. Vertex AI (Cloud Mode)
    if PROJECT_ID:
        try:
             vertexai.init(project=PROJECT_ID, location=LOCATION)
             model = GenerativeModel("gemini-2.5-flash") # Pinned Version
             print("SUCCESS: Vertex AI Initialized (Cloud Mode). Model: gemini-2.5-flash")
        except Exception as v_err:
             print(f"CRITICAL: Vertex AI Init Failed for project {PROJECT_ID} in {LOCATION}. Error: {v_err}")
             raise v_err
    
    # 2. Google AI Studio (Local Mode Fallback)
    elif GEMINI_API_KEY:
        import google.generativeai as genai
        genai.configure(api_key=GEMINI_API_KEY)
        model = genai.GenerativeModel("gemini-2.5-flash") # Pinned Version
        print("SUCCESS: Google AI Studio Initialized (Local Mode). Model: gemini-2.5-flash")
    
    else:
        print("CRITICAL WARNING: No GCP Project AND No Gemini API Key found. AI features will fail.")
        model = None

    # 3. Firestore
    if PROJECT_ID:
        db = firestore.Client(project=PROJECT_ID)
        print("SUCCESS: Firestore Initialized.")
    else:
        print("WARNING: Firestore not available (No Project ID). Persistence disabled.")
        db = None

    # 4. Cloud Storage
    if PROJECT_ID:
        storage_client = storage.Client(project=PROJECT_ID)
        print("SUCCESS: Storage Initialized.")
    else:
        print("WARNING: Cloud Storage not available (No Project ID). Uploads disabled.")
        storage_client = None

except Exception as e:
    print(f"CRITICAL ERROR - INIT FAILED: {e}")
    model = None
    db = None
    storage_client = None

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
    "mermaid_diagram": "graph TD; A[Concept] --> B[Result]; ..." 
    (REQUIRED. RULES for Mermaid: 
     1. ALWAYS use 'graph TD'.
     2. ALWAYS use square brackets and quotes for ALL node labels: id["Label Text"]. Ex: A["Kernel of T"].
     3. DO NOT use parentheses () for defining nodes. Use [] only.
     4. Use standard edge labels: A -->|Label| B. DO NOT use text strings directly on lines like 'A -- "Text" --> B'.
     5. Math equations MUST be strictly enclosed in quotes: id["A + B = C"]. Do NOT use unquoted math symbols like = or + outside quotes.
     6. NO HTML tags. Use plain text.
     7. NO special characters in node IDs (use alphanumeric only, e.g. Node1).
     8. Keep labels concise.)
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
    user_profile: str = "General" # Default for backward compatibility

class PodcastRequest(BaseModel):
    transcript_text: str
    user_profile: str = "General"

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
        
        # USE STRUCTURED PROMPTS (Safety)
        system_instruction = SYSTEM_PROMPT_TEMPLATE.format(profile_instruction=profile_instruction)
        
        try:
            # 1. SETUP CONTENT
            contents = []
            
            if video_uri:
                # MULTIMODAL VIDEO PROCESSING
                # Vertex AI automatically handles "soft caching" for GCS URIs in the backend optimization 
                # for repeated calls in short windows, but for explicit caching we would use caching.CachedContent.create.
                # For this MVP, using Part.from_uri is the correct efficient way vs bytes.
                print(f"DEBUG: Processing Video from {video_uri}")
                mime_type, _ = mimetypes.guess_type(video_uri)
                if not mime_type: mime_type = "video/mp4"
                
                video_part = Part.from_uri(uri=video_uri, mime_type=mime_type)
                # Structured User Prompt
                contents = [
                   # System instruction is handled by model init usually, but for 1.5 we can pass as first logic
                   # or use system_instruction arg in GenerativeModel (if supported by lib ver).
                   # keeping it simple:
                   Content(role="user", parts=[
                        Part.from_text(system_instruction), 
                        video_part, 
                        Part.from_text("Analyze this content.")
                   ])
                ]
            else:
                # TEXT PROCESSING
                # CACHING LOGIC: If transcript is huge (>32k), we *should* use context caching.
                # MVP Logic: Just pass it.
                contents = [
                    Content(role="user", parts=[
                        Part.from_text(system_instruction),
                        Part.from_text(f"TRANSCRIPT:\n{transcript[:25000]}...")
                    ])
                ]

            # RETRY LOGIC
            max_retries = 3
            base_delay = 2
            
            for attempt in range(max_retries):
                try:
                    response = model.generate_content(
                        contents,
                        generation_config=GenerationConfig(response_mime_type="application/json")
                    )
                    return response.text
                except Exception as e:
                    if "429" in str(e) and attempt < max_retries - 1:
                        sleep_time = base_delay * (2 ** attempt) + random.uniform(0, 1)
                        print(f"Quota Hit (429). Retrying in {sleep_time:.2f}s...")
                        time.sleep(sleep_time)
                    else:
                        raise e
                        
        except Exception as e:
            print(f"Vertex Generation Error: {e}")
            return f"{{\"summary\": \"AI Error: {str(e)}\", \"focus_points\": []}}"

    @staticmethod
    def generate_podcast_script(transcript: str, profile: str):
        if not model:
            raise HTTPException(status_code=500, detail="Vertex AI is not connected.")
            
        # DYNAMIC PODCAST PERSONAS
        persona_setup = ""
        if "Hinglish" in profile:
             persona_setup = """
             **STYLE:** Viral Indian Study Podcast. Fun, informal, "Hinglish" (Hindi+English).
             **HOSTS:**
             - **Max:** Indian Gen-Z student. Uses slang ("Arre sir", "Matlab?", "Bhai"). Energetic.
             - **Dr. V:** Patient professor. Explains consistently but simply.
             """
        elif "ADHD" in profile:
             persona_setup = """
             **STYLE:** High-Dopamine, Fast-Paced. NO boring lectures.
             **HOSTS:**
             - **Max:** Hyper-curious student. Interrupts often. Needs constant examples.
             - **Dr. V:** Expert who uses wild analogies (e.g., "Imagine the cell is a pizza factory").
             """
        elif "Dyslexia" in profile:
             persona_setup = """
             **STYLE:** Visual Audio. Focus on describing things vividly.
             **HOSTS:**
             - **Storyteller:** Uses narrative structure. "Picture this..."
             - **Guide:** Helps navigate the story.
             """
        else: # General / Research
             persona_setup = """
             **STYLE:** NPR / BBC Style Interview. Professional, dense, academic.
             **HOSTS:**
             - **Host:** Professional journalist.
             - **Expert:** Deep subject matter expert.
             """

        prompt = f"""
        You are a top-tier Educational Podcast Producer.
        
        {persona_setup}

        **TASK:** Convert this transcript into a script matching the STYLE and HOSTS above.
        **RULES:**
        1. Base purely on the text below.
        2. Keep it engaging.
        3. NO Stage directions (like *laughs*). Dialogue ONLY.
        
        **TRANSCRIPT:**
        {transcript[:15000]}
        """
        
        try:
            response = model.generate_content(prompt)
            return response.text
        except Exception as e:
             raise HTTPException(status_code=500, detail=f"Vertex AI Error: {str(e)}")

class DatabaseService:
    @staticmethod
    def save_lecture(user_id, video_id, summary_data, transcript_snippet, podcast_status="pending", podcast_script=None):
        if not db:
             print("Firestore not connected. Skipping save.")
             return "error-no-db"

        data = {
            "video_id": video_id,
            "status": "processed",
            "summary_data": summary_data,
            "context_snippet": transcript_snippet, 
            "timestamp": firestore.SERVER_TIMESTAMP,
            "podcast_status": podcast_status
        }
        if podcast_script:
            data["podcast_script"] = podcast_script
            data["podcast_generated_at"] = firestore.SERVER_TIMESTAMP
        
        doc_ref = db.collection("users").document(user_id).collection("lectures").document(video_id)
        doc_ref.set(data, merge=True)
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
            # Check for cookies.txt
            cookie_file = 'cookies.txt' if os.path.exists('cookies.txt') else None

            # 1. Try to find ANY transcript (Manual OR Auto-generated)
            if cookie_file:
                 transcript_list = YouTubeTranscriptApi.list_transcripts(video_id, cookies=cookie_file)
            else:
                 transcript_list = YouTubeTranscriptApi.list_transcripts(video_id)
            
            # Prefer English, but take anything we can find
            try:
                transcript = transcript_list.find_transcript(['en', 'en-US', 'en-GB', 'hi', 'hi-IN'])
            except:
                # If no English, just take the first one available (e.g. Hindi, Spanish)
                transcript = next(iter(transcript_list))
                
            full_text = " ".join([t['text'] for t in transcript.fetch()])
            ai_response = CognitiveService.generate_content(full_text, payload.user_profile)
            
        except Exception as e:
            print(f"Transcript Fetch Failed ({e}). Attempting Audio Download...")
            
            # 2. FALLBACK: Server-Side Audio Download (yt-dlp)
            try:
                ydl_opts = {
                    'format': 'bestaudio/best',
                    'outtmpl': f'/tmp/{video_id}.%(ext)s',
                    'postprocessors': [{'key': 'FFmpegExtractAudio','preferredcodec': 'mp3',}],
                    'quiet': True,
                    'socket_timeout': 10,
                    'extractor_args': {'youtube': {'player_client': ['android', 'web']}} 
                }
                if os.path.exists('cookies.txt'):
                    ydl_opts['cookiefile'] = 'cookies.txt'

                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    ydl.download([payload.video_url])
                
                # Upload to GCS
                if storage_client:
                    bucket = storage_client.bucket(BUCKET_NAME)
                    blob = bucket.blob(f"audio_cache/{video_id}.mp3")
                    blob.upload_from_filename(f"/tmp/{video_id}.mp3")
                    
                    audio_uri = f"gs://{BUCKET_NAME}/audio_cache/{video_id}.mp3"
                else: 
                     audio_uri = None
                     raise Exception("Storage not available for audio fallback")

                full_text = "Audio Content (Processed via Multimodal AI)"
                ai_response = CognitiveService.generate_content("", payload.user_profile, video_uri=audio_uri)
                
            except Exception as dl_error: 
                print(f"Audio Fallback Failed: {dl_error}")
                # 3. FINAL FALLBACK: Ask User to Upload
                raise HTTPException(
                    status_code=400, 
                    detail="Synapse could not access this video (YouTube might be blocking Cloud Servers). SOLUTION: Please download this video manually and use the 'Upload Video' button!"
                )
            finally:
                # 4. CLEANUP EPHEMERAL FILES
                local_audio_path = f"/tmp/{video_id}.mp3"
                if os.path.exists(local_audio_path):
                    try:
                        os.remove(local_audio_path)
                        print(f"Cleanup: Removed {local_audio_path}")
                    except Exception as cleanup_err:
                        print(f"Cleanup Error: {cleanup_err}")


    # GENERATE PODCAST SYNCHRONOUSLY (BLOCKING) for MVP Reliability
    podcast_script = ""
    podcast_status = "failed"
    try:
        # Determine source for podcast
        podcast_source = full_text if full_text and not full_text.startswith("Video Content") and not full_text.startswith("Audio Content") else ""
        if not podcast_source:
             # Fallback: use summary
             import json
             try:
                 summary_data = json.loads(ai_response)
                 podcast_source = summary_data.get('summary', '')
             except:
                 pass
        
        if podcast_source:
             podcast_script = CognitiveService.generate_podcast_script(podcast_source[:15000], payload.user_profile)
             podcast_status = "ready"
        else:
             print("Warning: No text source available for podcast generation.")
             
    except Exception as e:
        print(f"Podcast Generation Failed: {e}")
        podcast_status = "failed"

    DatabaseService.save_lecture(payload.user_id, video_id, ai_response, full_text[:10000], podcast_status=podcast_status, podcast_script=podcast_script)
    
    return {
        "status": "success", 
        "lecture_id": video_id, 
        "content": ai_response,
        "transcript_context": full_text[:5000],
        "podcast_status": podcast_status,
        "podcast_script": podcast_script
    }

@app.post("/api/v1/generate-podcast")
async def generate_podcast_endpoint(payload: PodcastRequest):
    script = CognitiveService.generate_podcast_script(payload.transcript_text, payload.user_profile)
    return {"script": script}

@app.get("/api/v1/podcast-status/{user_id}/{lecture_id}")
async def check_podcast_status(user_id: str, lecture_id: str):
    """Check if podcast is ready"""
    try:
        print(f"Checking podcast status for user_id={user_id}, lecture_id={lecture_id}")
        doc_ref = db.collection('users').document(user_id).collection('lectures').document(lecture_id)
        print(f"Firestore path: users/{user_id}/lectures/{lecture_id}")
        
        doc = doc_ref.get()
        print(f"Document exists: {doc.exists}")
        
        if not doc.exists:
            # List all lectures for this user to help debug
            all_lectures = db.collection('users').document(user_id).collection('lectures').stream()
            lecture_ids = [doc.id for doc in all_lectures]
            print(f"Available lecture IDs for user {user_id}: {lecture_ids}")
            raise HTTPException(status_code=404, detail=f"Lecture not found. Available IDs: {lecture_ids}")
        
        data = doc.to_dict()
        print(f"Document data keys: {list(data.keys())}")
        return {
            "status": data.get('podcast_status', 'unknown'),
            "script": data.get('podcast_script', ''),
            "error": data.get('podcast_error')
        }
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error checking podcast status: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))



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
    
    # SANITIZATION WARNING: In a real prod env, we should use the `Part` object or ChatSession
    # to strictly separate User input from System instructions.
    
    if model:
        try:
             # Basic injection safety: Wrap user input in explicit delimiters in future iterations
            response = model.generate_content(chat_prompt)
            return {"answer": response.text}
        except Exception as e:
            return {"answer": f"AI Error: {str(e)}"}
    else:
        return {"answer": "AI not connected."}


