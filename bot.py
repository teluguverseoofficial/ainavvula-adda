import asyncio
import json
import os
import random
import subprocess
import sys
import time
import urllib.parse
import requests
import edge_tts
from google import genai
from google.genai import types
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

sys.stdout.reconfigure(line_buffering=True)

GEMINI_KEY = os.environ["GEMINI_API_KEY"]
PIXABAY_KEY = os.environ["PIXABAY_API_KEY"]

client = genai.Client(
    api_key=GEMINI_KEY,
    http_options=types.HttpOptions(timeout=30000)
)

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
    Create a fast-paced 40-second faceless YouTube Short script for a US audience about a {chosen_angle}.
    Rules:
    - Start with a shocking hook in the first 3 seconds (no 'Hey guys' or intros).
    - Explain the exact steps clearly so anyone can try it immediately.
    - End with a short question to drive comments.
    - STRICT LENGTH: Keep the spoken script between 85 and 100 words so the audio is under 50 seconds.
    
    Return strictly valid JSON with keys:
    "title": catchy title under 55 chars ending with #Shorts,
    "description": 2-sentence summary + relevant hashtags,
    "search_keyword": 1 or 2-word Pixabay video query (e.g. "computer", "technology", "smartphone", "coding"),
    "script": the spoken narration text only
    """

    models_to_try = [
        "gemini-3.5-flash-lite",
        "gemini-3.8-flash"
    ]

    last_error = None
    for model_name in models_to_try:
        for attempt in range(2):
            try:
                print(f"[1/5] Generating script with {model_name} (attempt {attempt + 1})...")
                response = client.models.generate_content(
                    model=model_name,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        response_mime_type="application/json"
                    )
                )
                return json.loads(response.text)
            except Exception as e:
                print(f"Model {model_name} failed: {e}")
                last_error = e
                time.sleep(3)

    raise RuntimeError(f"All Gemini models failed: {last_error}")

# 2. GENERATE AMERICAN VOICEOVER + WORD-LEVEL SUBTITLES (.SRT)
async def generate_voice_and_subs(script_text):
    print("[2/5] Generating voiceover and subtitles...")
    
    # Sanitize text so special characters don't crash the Edge TTS XML parser
    clean_text = script_text.replace('*', '').replace('#', '').replace('"', '').replace('&', 'and').strip()
    
    # Auto-retry loop in case Microsoft servers drop the connection
    for attempt in range(3):
        try:
            communicate = edge_tts.Communicate(
                clean_text,
                "en-US-AndrewNeural",
                rate="+10%",
                boundary="WordBoundary"
            )
            submaker = edge_tts.SubMaker()
            
            with open("voice.mp3", "wb") as audio_file:
                async for chunk in communicate.stream():
                    if chunk["type"] == "audio":
                        audio_file.write(chunk["data"])
                    elif chunk["type"] in ("WordBoundary", "SentenceBoundary"):
                        submaker.feed(chunk)

            srt_content = submaker.get_srt().strip()
            if not srt_content:
                srt_content = f"1\n00:00:00,000 --> 00:00:55,000\n{clean_text}\n"

            with open("subs.srt", "w", encoding="utf-8") as srt_file:
                srt_file.write(srt_content + "\n")
            print(f"Saved subs.srt ({len(srt_content)} bytes)")
            return # Success! Exit the function.
            
        except Exception as e:
            print(f"TTS Attempt {attempt + 1} failed: {e}")
            time.sleep(3)
            
    raise RuntimeError("Edge TTS failed after 3 attempts.")

# 3. FETCH HD TECH B-ROLL FROM PIXABAY
def fetch_background_video(keyword):
    print(f"[3/5] Fetching Pixabay B-roll for '{keyword}'...")
    encoded_query = urllib.parse.quote(keyword)
    url = f"https://pixabay.com/api/videos/?key={PIXABAY_KEY}&q={encoded_query}&per_page=10"
    res = requests.get(url, timeout=20).json()
    
    hits = res.get("hits", [])
    if not hits:
        res = requests.get(
            f"https://pixabay.com/api/videos/?key={PIXABAY_KEY}&q=technology&per_page=10",
            timeout=20
        ).json()
        hits = res["hits"]
        
    chosen = random.choice(hits)
    videos = chosen["videos"]
    video_url = videos.get("medium", {}).get("url") or videos.get("large", {}).get("url")
    
    video_data = requests.get(video_url, timeout=30).content
    with open("bg.mp4", "wb") as f:
        f.write(video_data)

# 4. RENDER 1080x1920 VERTICAL SHORT (STRICTLY UNDER 58 SECONDS)
def render_video():
    print("[4/5] Rendering 1080x1920 video with FFmpeg (max 58s)...")
    style = (
        "FontName=DejaVu Sans,"
        "FontSize=18,"
        "PrimaryColour=&H0000FFFF,"
        "OutlineColour=&H00000000,"
        "BorderStyle=1,"
        "Outline=2,"
        "Alignment=10,"
        "MarginV=120"
    )
    vf_filter = (
        "scale=1080:1920:force_original_aspect_ratio=increase,"
        "crop=1080:1920,"
        "eq=brightness=-0.08,"
        f"subtitles=subs.srt:force_style='{style}'"
    )
    cmd = [
        "ffmpeg", "-y",
        "-stream_loop", "-1", "-i", "bg.mp4",
        "-i", "voice.mp3",
        "-vf", vf_filter,
        "-map", "0:v:0", "-map", "1:a:0",
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "24",
        "-c:a", "aac", "-b:a", "128k",
        "-t", "58",
        "-shortest", "final_short.mp4"
    ]
    subprocess.run(cmd, check=True)

# 5. UPLOAD TO YOUTUBE DATA API V3
def upload_to_youtube(metadata):
    print("[5/5] Uploading video to YouTube...")
    creds = Credentials.from_authorized_user_file(
        "token.json", ["https://www.googleapis.com/auth/youtube.upload"]
    )
    youtube = build("youtube", "v3", credentials=creds)

    body = {
        "snippet": {
            "title": metadata["title"][:100],
            "description": f"{metadata['description']}\n\n#Shorts #TechHacks #AITools #Productivity",
            "tags": ["Shorts", "TechHacks", "AI", "ComputerTricks", "Productivity"],
            "categoryId": "28"
        },
        "status": {
            "privacyStatus": "public",
            "selfDeclaredMadeForKids": False
        }
    }

    media = MediaFileUpload("final_short.mp4", chunksize=-1, resumable=True)
    request = youtube.videos().insert(part="snippet,status", body=body, media_body=media)
    response = request.execute()
    print(f"Uploaded successfully! Video ID: {response['id']}")

if __name__ == "__main__":
    data = generate_tech_hack()
    print("Generated Topic:", data["title"])
    asyncio.run(generate_voice_and_subs(data["script"]))
    fetch_background_video(data["search_keyword"])
    render_video()
    upload_to_youtube(data)
