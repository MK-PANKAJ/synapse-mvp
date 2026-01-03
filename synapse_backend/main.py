import os
import vertexai
from vertexai.generative_models import GenerativeModel
from google.cloud import firestore
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from youtube_transcript_api import YouTubeTranscriptApi
from typing import List, Optional
from python_dotenv import load_dotenv

load_dotenv()

# --- CONFIGURATION ---
PROJECT_ID = os.getenv("GCP_PROJECT", "your-project-id")
LOCATION = "us-central1"

# Initialize Google Cloud Services
try:
    vertexai.init(project=PROJECT_ID, location=LOCATION)
    model = GenerativeModel("gemini-1.5-pro-001") # Adjusted to stable model name for safety
except Exception as e:
    print(f"Warning: Vertex AI init failed: {e}")
    model = None

try:
    db = firestore.Client(project=PROJECT_ID)
except Exception as e:
    print(f"Warning: Firestore init failed: {e}")
    db = None

app = FastAPI(title="Synapse API", version="1.0-Final")

# --- DATA MODELS ---
class VideoIngest(BaseModel):
    user_id: str
    video_url: str
    user_profile: str  # "ADHD", "Dyslexia", "ESL"

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
            return "Format: High-energy, emoji-bullet points. Max 3 bullets. Focus on 'Why this matters'."
        if "Dyslexia" in profile:
            return "Format: Simple syntax. Use visual metaphors. Avoid dense paragraphs."
        return "Format: Clear, academic summary."

    @staticmethod
    def generate_content(transcript: str, profile: str):
        if not model:
            return "Simulated AI Summary: Vertex AI not connected."
            
        system_instruction = CognitiveService.get_prompt_logic(profile)
        prompt = f"""
        ROLE: Expert Educational Neuro-adapter.
        INSTRUCTION: {system_instruction}
        TASK: Analyze this transcript.
        1. Create a structured learning card summary.
        2. Extract exactly 9 "Bingo Keywords" (single words or short phrases) that are central to the topic.
        
        TRANSCRIPT: {transcript[:10000]}... (truncated for context limit)

        OUTPUT FORMAT (Strict JSON):
        {{
            "summary": "markdown_text_here",
            "bingo_terms": ["term1", "term2", "term3", ...]
        }}
        """
        try:
            # We urge the model to return JSON. In a real app, use response_schema if supported or strict parsing.
            response = model.generate_content(prompt)
            # For this MVP, we will assume the model obeys or we might need simple parsing.
            # To be safe for the demo, we'll return the raw text and let frontend/parsing handle it, 
            # Or we can try to parse it here. For simplicity in MVP, we might return text if parsing fails.
            return response.text
        except Exception as e:
            return f"{{\"summary\": \"Error generating content: {str(e)}\", \"bingo_terms\": []}}"

    @staticmethod
    def generate_podcast_script(transcript: str):
        if not model:
            return "Simulated Podcast: Vertex AI not connected."
            
        prompt = """
        You are an expert educational scriptwriter.
        Convert the provided lecture transcript into a dynamic podcast script between two hosts:
        1. **Dr. V** (The wise, calm expert).
        2. **Max** (A high-energy, relatable student who uses analogies).

        Rules:
        - Max should interrupt politely when things get too abstract.
        - Use sound effect cues in brackets like [Sound: Page turning].
        - Keep the explanation accurate but change the tone to be conversational.
        - Output strictly the dialogue script.
        
        TRANSCRIPT:
        """ + transcript[:10000]
        
        try:
            response = model.generate_content(prompt)
            return response.text
        except Exception as e:
            return f"Error generating podcast: {str(e)}"

class DatabaseService:
    @staticmethod
    def save_lecture(user_id, video_id, summary_data, transcript_snippet):
        if not db:
            print("Firestore not connected. Skipping save.")
            return "mock-doc-id"
            
        # Saves to Firestore: users/{uid}/lectures/{video_id}
        doc_ref = db.collection("users").document(user_id).collection("lectures").document(video_id)
        doc_ref.set({
            "video_id": video_id,
            "status": "processed",
            "summary_data": summary_data, # Can be JSON string or dict
            "context_snippet": transcript_snippet, 
            "timestamp": firestore.SERVER_TIMESTAMP
        })
        return doc_ref.id

# --- API ENDPOINTS ---

@app.post("/api/v1/ingest")
async def ingest_lecture(payload: VideoIngest):
    try:
        # 1. Extract ID & Transcript
        video_id = ""
        if "v=" in payload.video_url:
            video_id = payload.video_url.split("v=")[1].split("&")[0]
        elif "youtu.be/" in payload.video_url:
             video_id = payload.video_url.split("youtu.be/")[1].split("?")[0]
        else:
             raise HTTPException(status_code=400, detail="Invalid YouTube URL")
        
        # 2. Get Transcript
        try:
            transcript_list = YouTubeTranscriptApi.get_transcript(video_id)
            full_text = " ".join([t['text'] for t in transcript_list])
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Transcript error: {str(e)}")
        
        # 3. AI Processing (Now returns JSON String typically)
        ai_response = CognitiveService.generate_content(full_text, payload.user_profile)
        
        # 4. Persistence
        DatabaseService.save_lecture(payload.user_id, video_id, ai_response, full_text[:10000])
        
        return {
            "status": "success", 
            "lecture_id": video_id, 
            "content": ai_response, # Expected to be JSON string with summary & bingo
            "transcript_context": full_text[:5000] # Sending back some context for podcast generation if needed
        }

    except HTTPException as he:
        raise he
    except Exception as e:
        print(f"Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/v1/generate-podcast")
async def generate_podcast_endpoint(payload: PodcastRequest):
    try:
        script = CognitiveService.generate_podcast_script(payload.transcript_text)
        return {"status": "success", "script": script}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/v1/ask-doubt")
async def solve_doubt(payload: DoubtQuery):
    try:
        # 1. Fetch Context from Firestore
        context = ""
        if db:
            doc_ref = db.collection("users").document(payload.user_id).collection("lectures").document(payload.lecture_id)
            doc = doc_ref.get()
            
            if not doc.exists:
                raise HTTPException(status_code=404, detail="Lecture context not found")
                
            context = doc.to_dict().get("context_snippet", "")
        else:
            context = "Mock context: Firestore not connected."
        
        # 2. Context-Aware AI Answer
        chat_prompt = f"""
        CONTEXT: {context}
        USER QUESTION: {payload.question}
        TASK: Answer in 2 sentences. Use an analogy.
        """
        
        if model:
            response = model.generate_content(chat_prompt)
            return {"answer": response.text}
        else:
            return {"answer": "This is a mock answer. (AI not connected)"}
        
    except HTTPException as he:
        raise he
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

