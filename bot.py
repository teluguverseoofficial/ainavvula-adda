import asyncio
import hashlib
import json
import os
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
HISTORY_FILE = "used_scenarios.json"

client = genai.Client(
    api_key=GEMINI_KEY,
    http_options=types.HttpOptions(timeout=60000)
)


def load_used_history():
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list):
                    return data
        except Exception as e:
            print(f"Could not read {HISTORY_FILE}, starting fresh: {e}", flush=True)
    return []


def save_used_history(history):
    # Keep the last 100 entries so the prompt stays compact while preventing repeats
    trimmed = history[-100:]
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(trimmed, f, ensure_ascii=False, indent=2)


# 1. FETCH CURRENT VIRAL SCENARIO & BUILD TELUGU AI COMEDY KIT (NO REPEATS)
def generate_viral_telugu_comedy_kit():
    history = load_used_history()
    recent_topics = [item.get("scenario_key", "") for item in history[-30:] if item.get("scenario_key")]
    avoid_list = ", ".join(recent_topics) if recent_topics else "None yet"

    prompt = f"""
    Search the web for currently trending viral comedy formats, memes, and relatable everyday Indian/Telugu social situations right now.
    Pick ONE fresh, punchy viral comedy scenario suitable for a 30-to-35 second Telugu YouTube Short.

    CRITICAL ANTI-REPEAT RULE:
    Do NOT pick or repeat any scenario similar to these already-used ones:
    [{avoid_list}]

    Rules for the output:
    - Write the spoken script in natural, conversational, witty Telugu (everyday spoken Telugu slang, NOT formal news Telugu).
    - Start with an immediate hook/punchline in the very first sentence.
    - Keep the spoken script between 55 and 70 words so pacing is fast and punchy.
    - Provide a short unique "scenario_key" (3-6 words in English summarizing the specific viral twist) so we never repeat it.
    - Provide 4 distinct English image prompts describing 3D Pixar-style expressive cartoon characters acting out the 4 beats of this exact viral comedy scenario in an Indian setting.

    Return strictly valid JSON with keys:
    "scenario_key": "short unique summary of this viral joke",
    "title": "catchy Telugu title with a funny hook ending with #Shorts #TeluguComedy #AIComedy",
    "description": "2-sentence funny Telugu summary + hashtags",
    "script": "spoken Telugu comedy text only (no stage directions or asterisks)",
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
                print(
                    f"[1/5] Fetching viral scenario & generating Telugu script with {model_name} (attempt {attempt + 1})...",
                    flush=True,
                )
                response = client.models.generate_content(
                    model=model_name,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        tools=[{"google_search": {}}],
                        response_mime_type="application/json",
                    ),
                )
                kit = json.loads(response.text)
                scenario_key = kit.get("scenario_key", "").strip()
                fingerprint = hashlib.sha256(
                    (scenario_key.lower() + "|" + kit.get("script", "").strip()).encode("utf-8")
                ).hexdigest()[:16]

                if any(entry.get("hash") == fingerprint for entry in history):
                    print("Duplicate scenario hash detected, retrying for a fresh viral angle...", flush=True)
                    continue

                history.append({
                    "hash": fingerprint,
                    "scenario_key": scenario_key,
                    "title": kit.get("title", ""),
                })
                save_used_history(history)
                return kit
            except Exception as e:
                print(f"Model {model_name} failed: {e}", flush=True)
                last_error = e
                time.sleep(3)

    raise RuntimeError(f"All Gemini models failed to generate a unique viral skit: {last_error}")


# 2. GENERATE EXPRESSIVE TELUGU VOICEOVER + SUBTITLES
async def generate_voice_and_subs(script_text):
    print("[2/5] Generating energetic Telugu comedy voiceover...", flush=True)
    clean_text = script_text.replace("*", "").replace("#", "").replace('"', "").strip()

    for attempt in range(3):
        try:
            communicate = edge_tts.Communicate(
                clean_text,
                "te-IN-MohanNeural",
                rate="+8%",
                pitch="+2Hz",
                boundary="SentenceBoundary",
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
        full_prompt = (
            f"{prompt_text}, vibrant colors, exaggerated funny facial expressions, "
            f"vertical 9:16 composition, high detail 3D render"
        )
        filename = f"scene_{idx}.png"
        try:
            result = client.models.generate_images(
                model="imagen-3.0-generate-002",
                prompt=full_prompt,
                config=types.GenerateImagesConfig(
                    number_of_images=1,
                    output_mime_type="image/png",
                    aspect_ratio="9:16",
                ),
            )
            for generated_image in result.generated_images:
                generated_image.image.save(filename)
            image_files.append(filename)
            print(f"Saved {filename}", flush=True)
        except Exception as e:
            print(f"Imagen failed on scene {idx}: {e}", flush=True)
            subprocess.run(
                [
                    "ffmpeg", "-y", "-loglevel", "error",
                    "-f", "lavfi", "-i", "color=c=0x1a1a2e:s=1080x1920:d=1",
                    "-frames:v", "1", filename,
                ],
                check=True,
            )
            image_files.append(filename)

    return image_files


# 4. STITCH SCENES WITH ZOOM MOTION + BURN TELUGU SUBTITLES
def render_comedy_short(image_files):
    print("[4/5] Rendering 1080x1920 animated comic reel with FFmpeg...", flush=True)

    probe = subprocess.run(
        [
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            "voice.mp3",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    total_duration = float(probe.stdout.strip()) + 0.5
    clip_duration = total_duration / len(image_files)
    frames_per_clip = max(1, int(clip_duration * 30))

    clip_paths = []
    for idx, img in enumerate(image_files):
        clip_name = f"clip_{idx}.mp4"
        zoom_filter = (
            f"scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,"
            f"zoompan=z='min(zoom+0.0015,1.15)':d={frames_per_clip}:s=1080x1920:fps=30"
        )
        subprocess.run(
            [
                "ffmpeg", "-y", "-loglevel", "error",
                "-loop", "1", "-i", img,
                "-vf", zoom_filter,
                "-t", str(clip_duration),
                "-c:v", "libx264", "-pix_fmt", "yuv420p",
                clip_name,
            ],
            check=True,
        )
        clip_paths.append(clip_name)

    with open("concat.txt", "w", encoding="utf-8") as f:
        for c in clip_paths:
            f.write(f"file '{c}'\n")

    subprocess.run(
        [
            "ffmpeg", "-y", "-loglevel", "error",
            "-f", "concat", "-safe", "0", "-i", "concat.txt",
            "-c", "copy", "stitched_video.mp4",
        ],
        check=True,
    )

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

    subprocess.run(
        [
            "ffmpeg", "-y", "-loglevel", "error",
            "-i", "stitched_video.mp4",
            "-i", "voice.mp3",
            "-vf", f"subtitles=subs.srt:fontsdir={font_dir}:force_style='{style}'",
            "-map", "0:v:0", "-map", "1:a:0",
            "-c:v", "libx264", "-preset", "medium", "-crf", "18",
            "-c:a", "aac", "-b:a", "192k",
            "-shortest", "final_short.mp4",
        ],
        check=True,
    )


# 5. UPLOAD ONE VIDEO TO YOUTUBE WITH QUOTA SAFETY
def upload_to_youtube(metadata):
    print("[5/5] Uploading single Telugu comedy short to YouTube...", flush=True)
    creds = Credentials.from_authorized_user_file(
        "token.json", ["https://www.googleapis.com/auth/youtube.upload"]
    )
    youtube = build("youtube", "v3", credentials=creds)

    body = {
        "snippet": {
            "title": metadata["title"][:100],
            "description": f"{metadata['description']}\n\n#TeluguComedy #AIComedy #TeluguShorts #FunnyVideos #TrendingTelugu",
            "tags": ["TeluguComedy", "AIComedy", "TeluguShorts", "FunnyTelugu", "TrendingMemes", "Shorts"],
            "categoryId": "23",
        },
        "status": {
            "privacyStatus": "public",
            "selfDeclaredMadeForKids": False,
        },
    }

    try:
        media = MediaFileUpload("final_short.mp4", chunksize=-1, resumable=True)
        request = youtube.videos().insert(part="snippet,status", body=body, media_body=media)
        response = request.execute()
        print(f"Uploaded successfully! Video ID: {response['id']}", flush=True)
    except Exception as e:
        print(f"Upload skipped/limited by YouTube quota: {e}", flush=True)


if __name__ == "__main__":
    kit = generate_viral_telugu_comedy_kit()
    print(f"Viral Scenario: {kit.get('scenario_key', '')}", flush=True)
    print(f"Generated Comedy Title: {kit['title']}", flush=True)
    asyncio.run(generate_voice_and_subs(kit["script"]))
    scenes = generate_comic_scenes(kit["scene_prompts"])
    render_comedy_short(scenes)
    upload_to_youtube(kit)
