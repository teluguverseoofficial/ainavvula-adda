import asyncio
import json
import os
import random
import subprocess
import sys
import time
import edge_tts
from google import genai
from google.genai import types
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

sys.stdout.reconfigure(line_buffering=True)

GEMINI_KEY = os.environ["GEMINI_API_KEY"]

client = genai.Client(
    api_key=GEMINI_KEY,
    http_options=types.HttpOptions(timeout=60000)
)

# 1. GENERATE RELATABLE TELUGU COMEDY SKIT & 4 SCENE PROMPTS
def generate_telugu_comedy_kit():
    scenarios = [
        "a funny argument between a lazy Telugu IT employee and his strict manager on a Monday morning call",
        "a hilarious middle-class Telugu mom scolding her son about spending all day on his phone instead of getting married",
        "two broke Telugu friends at a roadside Irani chai stall arguing over who has to pay the 30 rupee bill",
        "a funny situation where a guy tries to impress his crush with fake English and gets caught immediately",
        "a relatable Telugu exam hall panic where two best friends try to copy from each other and both wrote wrong answers"
    ]
    chosen_scenario = random.choice(scenarios)

    prompt = f"""
    Create a punchy, high-retention 30-to-35 second Telugu comedy Shorts script about: {chosen_scenario}.
    
    Rules:
    - Write the spoken script in natural, conversational, witty Telugu (everyday spoken Telugu slang used in Hyderabad/Vijayawada, NOT formal news Telugu).
    - Start with a hilarious hook in the very first sentence.
    - Keep the spoken script between 55 and 70 words so the pacing is fast and snappy.
    - Provide 4 distinct English image generation prompts describing 3D Pixar-style expressive cartoon characters acting out the 4 beats of this exact joke in an Indian setting.
    
    Return strictly valid JSON with keys:
    "title": catchy Telugu title with a funny hook ending with #Shorts #TeluguComedy #AIComedy,
    "description": 2-sentence funny Telugu summary + hashtags,
    "script": spoken Telugu comedy monologue/dialogue text only (no stage directions or asterisks),
    "scene_prompts": [
        "3D Pixar animation style, expressive Indian character scene 1...",
        "3D Pixar animation style, expressive Indian character scene 2...",
        "3D Pixar animation style, expressive Indian character scene 3...",
        "3D Pixar animation style, expressive Indian character scene 4..."
    ]
    """

    models_to_try = ["gemini-2.5-flash", "gemini-2.0-flash"]
    last_error = None

    for model_name in models_to_try:
        for attempt in range(2):
            try:
                print(f"[1/5] Generating Telugu comedy script with {model_name} (attempt {attempt + 1})...", flush=True)
                response = client.models.generate_content(
                    model=model_name,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        response_mime_type="application/json"
                    )
                )
                return json.loads(response.text)
            except Exception as e:
                print(f"Model {model_name} failed: {e}", flush=True)
                last_error = e
                time.sleep(3)

    raise RuntimeError(f"All Gemini text models failed: {last_error}")

# 2. GENERATE EXPRESSIVE TELUGU VOICEOVER + SUBTITLES
async def generate_voice_and_subs(script_text):
    print("[2/5] Generating energetic Telugu comedy voiceover...", flush=True)
    clean_text = script_text.replace('*', '').replace('#', '').replace('"', '').strip()

    for attempt in range(3):
        try:
            communicate = edge_tts.Communicate(
                clean_text,
                "te-IN-MohanNeural",  # Male Telugu voice, punchier for comedy skits
                rate="+8%",           # Slightly faster pacing for YouTube Shorts retention
                pitch="+2Hz",
                boundary="SentenceBoundary"
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
                srt_content = f"1\n00:00:00,000 --> 00:00:35,000\n{clean_text}\n"

            with open("subs.srt", "w", encoding="utf-8") as srt_file:
                srt_file.write(srt_content + "\n")
            print("Voiceover and Telugu subtitles saved.", flush=True)
            return
        except Exception as e:
            print(f"TTS attempt {attempt + 1} failed: {e}", flush=True)
            time.sleep(3)

    raise RuntimeError("Edge TTS failed after 3 attempts.")

# 3. GENERATE 4 CUSTOM 3D COMIC SCENES USING IMAGEN
def generate_comic_scenes(scene_prompts):
    print("[3/5] Generating 4 custom AI comic scenes...", flush=True)
    image_files = []

    for idx, prompt_text in enumerate(scene_prompts[:4]):
        full_prompt = f"{prompt_text}, vibrant colors, exaggerated funny facial expressions, vertical 9:16 composition, high detail 3D render"
        filename = f"scene_{idx}.png"
        try:
            result = client.models.generate_images(
                model="imagen-3.0-generate-002",
                prompt=full_prompt,
                config=types.GenerateImagesConfig(
                    number_of_images=1,
                    output_mime_type="image/png",
                    aspect_ratio="9:16"
                )
            )
            for generated_image in result.generated_images:
                generated_image.image.save(filename)
            image_files.append(filename)
            print(f"Saved {filename}", flush=True)
        except Exception as e:
            print(f"Imagen failed on scene {idx}: {e}", flush=True)
            # Fallback dark comic gradient frame if quota hits on an image
            subprocess.run([
                "ffmpeg", "-y", "-loglevel", "error",
                "-f", "lavfi", "-i", "color=c=0x1a1a2e:s=1080x1920:d=1",
                "-frames:v", "1", filename
            ], check=True)
            image_files.append(filename)

    return image_files

# 4. STITCH SCENES WITH ZOOM MOTION + BURN TELUGU SUBTITLES
def render_comedy_short(image_files):
    print("[4/5] Rendering 1080x1920 animated comic reel with FFmpeg...", flush=True)

    # Get exact audio duration so visuals match voiceover perfectly
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", "voice.mp3"],
        capture_output=True, text=True, check=True
    )
    total_duration = float(probe.stdout.strip()) + 0.5
    clip_duration = total_duration / len(image_files)
    frames_per_clip = int(clip_duration * 30)

    # Create animated zoom-in clips for each scene
    clip_paths = []
    for idx, img in enumerate(image_files):
        clip_name = f"clip_{idx}.mp4"
        zoom_filter = (
            f"scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,"
            f"zoompan=z='min(zoom+0.0015,1.15)':d={frames_per_clip}:s=1080x1920:fps=30"
        )
        subprocess.run([
            "ffmpeg", "-y", "-loglevel", "error",
            "-loop", "1", "-i", img,
            "-vf", zoom_filter,
            "-t", str(clip_duration),
            "-c:v", "libx264", "-pix_fmt", "yuv420p",
            clip_name
        ], check=True)
        clip_paths.append(clip_name)

    with open("concat.txt", "w") as f:
        for c in clip_paths:
            f.write(f"file '{c}'\n")

    subprocess.run([
        "ffmpeg", "-y", "-loglevel", "error",
        "-f", "concat", "-safe", "0", "-i", "concat.txt",
        "-c", "copy", "stitched_video.mp4"
    ], check=True)

    # Burn crisp Telugu subtitles using Lohit-Telugu font
    font_dir = os.path.expanduser("~/.fonts")
    style = (
        "FontName=Lohit Telugu,"
        "FontSize=22,"
        "PrimaryColour=&H0000FFFF,"
        "OutlineColour=&H00000000,"
        "BackColour=&H80000000,"
        "BorderStyle=4,"
        "Outline=2,"
        "Alignment=2,"
        "MarginV=240"
    )

    subprocess.run([
        "ffmpeg", "-y", "-loglevel", "error",
        "-i", "stitched_video.mp4",
        "-i", "voice.mp3",
        "-vf", f"subtitles=subs.srt:fontsdir={font_dir}:force_style='{style}'",
        "-map", "0:v:0", "-map", "1:a:0",
        "-c:v", "libx264", "-preset", "medium", "-crf", "18",
        "-c:a", "aac", "-b:a", "192k",
        "-shortest", "final_short.mp4"
    ], check=True)

# 5. UPLOAD TO YOUTUBE WITH QUOTA SAFETY
def upload_to_youtube(metadata):
    print("[5/5] Uploading Telugu comedy short to YouTube...", flush=True)
    creds = Credentials.from_authorized_user_file(
        "token.json", ["https://www.googleapis.com/auth/youtube.upload"]
    )
    youtube = build("youtube", "v3", credentials=creds)

    body = {
        "snippet": {
            "title": metadata["title"][:100],
            "description": f"{metadata['description']}\n\n#TeluguComedy #AIComedy #TeluguShorts #FunnyVideos #Navvulu",
            "tags": ["TeluguComedy", "AIComedy", "TeluguShorts", "FunnyTelugu", "TeluguMemes", "Shorts"],
            "categoryId": "23"  # Comedy Category ID
        },
        "status": {
            "privacyStatus": "public",
            "selfDeclaredMadeForKids": False
        }
    }

    try:
        media = MediaFileUpload("final_short.mp4", chunksize=-1, resumable=True)
        request = youtube.videos().insert(part="snippet,status", body=body, media_body=media)
        response = request.execute()
        print(f"Uploaded successfully! Video ID: {response['id']}", flush=True)
    except Exception as e:
        print(f"Upload skipped/limited by YouTube quota: {e}", flush=True)

if __name__ == "__main__":
    kit = generate_telugu_comedy_kit()
    print(f"Generated Comedy Title: {kit['title']}", flush=True)
    asyncio.run(generate_voice_and_subs(kit["script"]))
    scenes = generate_comic_scenes(kit["scene_prompts"])
    render_comedy_short(scenes)
    upload_to_youtube(kit)
