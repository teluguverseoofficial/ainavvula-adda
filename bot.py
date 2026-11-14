import asyncio
import json
import os
import random
import subprocess
import urllib.parse
import requests
import edge_tts
from google import genai
from google.genai import types
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

GEMINI_KEY = os.environ["GEMINI_API_KEY"]
PIXABAY_KEY = os.environ["PIXABAY_API_KEY"]

client = genai.Client(api_key=GEMINI_KEY)

# 1. GENERATE VIRAL TECH HACK SCRIPT + METADATA
def generate_tech_hack():
    angles = [
        "hidden Windows or Mac keyboard shortcut that saves hours",
        "mind-blowing free AI website nobody talks about",
        "hidden iPhone or Android setting that boosts speed or privacy",
        "secret Google Chrome trick or productivity hack",
        "free open-source alternative to expensive software"
    ]
    chosen_angle = random.choice(angles)

    prompt = f"""
    Create a fast-paced 45-second faceless YouTube Short script for a US audience about a {chosen_angle}.
    Rules:
    - Start with a shocking hook in the first 3 seconds (no 'Hey guys' or intros).
    - Explain the exact steps clearly so anyone can try it immediately.
    - End with a short question to drive comments.
    - Keep the spoken script between 95 and 115 words.
    
    Return strictly valid JSON with keys:
    "title": catchy title under 55 chars ending with #Shorts,
    "description": 2-sentence summary + relevant hashtags,
    "search_keyword": 1 or 2-word Pixabay video query (e.g. "computer", "technology", "smartphone", "coding"),
    "script": the spoken narration text only
    """
    response = client.models.generate_content(
        model="gemini-3.8-flash",
        contents=prompt,
        config=types.GenerateContentConfig(
            response_mime_type="application/json"
        )
    )
    return json.loads(response.text)

# 2. GENERATE AMERICAN VOICEOVER + WORD-LEVEL SUBTITLES (.SRT)
async def generate_voice_and_subs(script_text):
    communicate = edge_tts.Communicate(script_text, "en-US-AndrewNeural", rate="+10%")
    submaker = edge_tts.SubMaker()
    
    with open("voice.mp3", "wb") as audio_file:
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                audio_file.write(chunk["data"])
            elif chunk["type"] == "WordBoundary":
                submaker.feed(chunk)

    with open("subs.srt", "w", encoding="utf-8") as srt_file:
        srt_file.write(submaker.get_srt())

# 3. FETCH HD TECH B-ROLL FROM PIXABAY
def fetch_background_video(keyword):
    encoded_query = urllib.parse.quote(keyword)
    url = f"https://pixabay.com/api/videos/?key={PIXABAY_KEY}&q={encoded_query}&per_page=10"
    res = requests.get(url).json()
    
    hits = res.get("hits", [])
    if not hits:
        res = requests.get(f"https://pixabay.com/api/videos/?key={PIXABAY_KEY}&q=technology&per_page=10").json()
        hits = res["hits"]
        
    chosen = random.choice(hits)
    videos = chosen["videos"]
    video_url = videos.get("medium", {}).get("url") or videos.get("large", {}).get("url")
    
    with open("bg.mp4", "wb") as f:
        f.write(requests.get(video_url).content)

# 4. RENDER 1080x1920 VERTICAL SHORT WITH BURNED-IN CAPTIONS (FFMPEG)
def render_video():
    vf_filter = (
        "scale=1080:1920:force_original_aspect_ratio=increase,"
        "crop=1080:1920,"
        "eq=brightness=-0.08,"
        "subtitles=subs.srt:force_style='FontName=DejaVu Sans,FontSize
