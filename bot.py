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
from PIL import Image, ImageDraw, ImageFont

sys.stdout.reconfigure(line_buffering=True)

GEMINI_KEY = os.environ["GEMINI_API_KEY"]
HISTORY_FILE = "used_scenarios.json"
FONT_PATH = os.path.expanduser("~/.fonts/Lohit-Telugu.ttf")

client = genai.Client(
    api_key=GEMINI_KEY,
    http_options=types.HttpOptions(timeout=60000),
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
    trimmed = history[-100:]
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(trimmed, f, ensure_ascii=False, indent=2)


def _load_telugu_font(size: int):
    if os.path.exists(FONT_PATH):
        try:
            return ImageFont.truetype(FONT_PATH, size=size)
        except Exception:
            pass
    return ImageFont.load_default()


def _wrap_text(draw: ImageDraw.ImageDraw, text: str, font, max_width: int):
    words = text.split()
    if not words:
        return []
    lines = []
    current = words[0]
    for word in words[1:]:
        test = f"{current} {word}"
        bbox = draw.textbbox((0, 0), test, font=font)
        if (bbox[2] - bbox[0]) <= max_width:
            current = test
        else:
            lines.append(current)
            current = word
    lines.append(current)
    return lines


# 1. GENERATE FRESH TELUGU COMEDY KIT ON FREE TIER (NO SEARCH GROUNDING, NO REPEATS)
def generate_viral_telugu_comedy_kit():
    history = load_used_history()
    recent_topics = [item.get("scenario_key", "") for item in history[-30:] if item.get("scenario_key")]
    avoid_list = ", ".join(recent_topics) if recent_topics else "None yet"

    prompt = f"""
    Create ONE fresh, punchy, relatable Telugu comedy Short script for the YouTube channel "AI Navvula Adda" (Indian/Telugu everyday comedy: office bosses, Telugu parents, friends at a chai stall, traffic excuses, wedding/function drama, or funny everyday twists).

    CRITICAL ANTI-REPEAT RULE:
    Do NOT pick or repeat any scenario similar to these already-used ones:
    [{avoid_list}]

    Rules for the output:
    - Write the spoken script in natural, conversational, witty Telugu (everyday spoken Telugu slang, NOT formal news Telugu).
    - Start with an immediate hook/punchline in the very first sentence.
    - Keep the spoken script between 55 and 70 words so pacing is fast and punchy.
    - Provide a short unique "scenario_key" (3-6 words in English summarizing the specific joke) so we never repeat it.
    - Provide 4 short, punchy beat captions ("scene_captions") in Telugu (2-5 words each) for the 4 comic panels.

    Return strictly valid JSON with keys:
    "scenario_key": "short unique summary of this joke",
    "title": "catchy Telugu title with a funny hook ending with #Shorts #AINavvulaAdda #TeluguComedy",
    "description": "2-sentence funny Telugu summary + hashtags",
    "script": "spoken Telugu comedy text only (no stage directions or asterisks)",
    "scene_captions": [
        "Beat 1 Telugu caption",
        "Beat 2 Telugu caption",
        "Beat 3 Telugu caption",
        "Beat 4 Telugu caption"
    ]
    """

    models_to_try = ["gemini-3.1-flash-lite", "gemini-3.5-flash-lite", "gemini-3.8-flash"]
    last_error = None

    for model_name in models_to_try:
        for attempt in range(2):
            try:
                print(
                    f"[1/5] Generating Telugu comedy script with {model_name} (attempt {attempt + 1})...",
                    flush=True,
                )
                response = client.models.generate_content(
                    model=model_name,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        response_mime_type="application/json",
                        temperature=1.0,
                    ),
                )
                kit = json.loads(response.text)
                scenario_key = kit.get("scenario_key", "").strip()
                fingerprint = hashlib.sha256(
                    (scenario_key.lower() + "|" + kit.get("script", "").strip()).encode("utf-8")
                ).hexdigest()[:16]

                if any(entry.get("hash") == fingerprint for entry in history):
                    print("Duplicate scenario hash detected, retrying for a fresh angle...", flush=True)
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
                sleep_sec = 10 if "429" in str(e) else 3
                time.sleep(sleep_sec)

    raise RuntimeError(f"All Gemini models failed to generate a unique skit: {last_error}")


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


# 3. GENERATE 4 VIBRANT COMIC SCENE CARDS LOCALLY (ZERO IMAGE API QUOTA NEEDED)
def generate_comic_scenes(scene_captions, scenario_key=""):
    print("[3/5] Generating 4 colorful Telugu comic scene cards locally...", flush=True)
    image_files = []

    palettes = [
        ((24, 34, 79), (255, 193, 7), (255, 87, 34)),
        ((15, 76, 92), (0, 229, 255), (255, 214, 0)),
        ((74, 20, 140), (255, 64, 129), (255, 235, 59)),
        ((27, 94, 32), (178, 255, 89), (255, 171, 0)),
    ]

    header_font = _load_telugu_font(44)
    caption_font = _load_telugu_font(68)
    badge_font = _load_telugu_font(34)

    for idx in range(4):
        caption = scene_captions[idx] if idx < len(scene_captions) else f"సీన్ {idx + 1}"
        bg_top, accent_primary, accent_secondary = palettes[idx % len(palettes)]
        filename = f"scene_{idx}.png"

        img = Image.new("RGB", (1080, 1920), bg_top)
        draw = ImageDraw.Draw(img)

        # Geometric comic burst & accent bands
        draw.polygon([(0, 0), (1080, 0), (1080, 520), (0, 740)], fill=accent_primary)
        draw.polygon([(0, 1360), (1080, 1150), (1080, 1920), (0, 1920)], fill=accent_secondary)
        draw.ellipse([(240, 560), (840, 1160)], fill=(20, 24, 48), outline=(255, 255, 255), width=8)

        # Channel header
        draw.text((60, 65), "AI Navvula Adda", fill=(15, 20, 40), font=header_font)
        draw.text((60, 125), f"SCENE {idx + 1} / 4", fill=(255, 255, 255), font=badge_font)

        # Center comic beat caption
        wrapped = _wrap_text(draw, caption, caption_font, max_width=520)
        line_height = 84
        start_y = 860 - (len(wrapped) * line_height) // 2
        for line_idx, line in enumerate(wrapped):
            bbox = draw.textbbox((0, 0), line, font=caption_font)
            text_w = bbox[2] - bbox[0]
            x = (1080 - text_w) // 2
            y = start_y + line_idx * line_height
            draw.text((x + 3, y + 3), line, fill=(0, 0, 0), font=caption_font)
            draw.text((x, y), line, fill=(255, 255, 255), font=caption_font)

        img.save(filename, format="PNG")
        image_files.append(filename)
        print(f"Saved {filename}", flush=True)

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


# 5. UPLOAD ONE VIDEO TO YOUTUBE WITH QUOTA SAFETY & TELUGU LANGUAGE TAGS
def upload_to_youtube(metadata):
    print("[5/5] Uploading single Telugu comedy short to YouTube...", flush=True)
    creds = Credentials.from_authorized_user_file(
        "token.json", ["https://www.googleapis.com/auth/youtube.upload"]
    )
    youtube = build("youtube", "v3", credentials=creds)

    body = {
        "snippet": {
            "title": metadata["title"][:100],
            "description": f"{metadata['description']}\n\n#AINavvulaAdda #TeluguComedy #AIComedy #TeluguShorts #FunnyVideos",
            "tags": ["AINavvulaAdda", "TeluguComedy", "AIComedy", "TeluguShorts", "FunnyTelugu", "Shorts"],
            "categoryId": "23",
            "defaultLanguage": "te",
            "defaultAudioLanguage": "te",
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
    scenes = generate_comic_scenes(kit.get("scene_captions", []), kit.get("scenario_key", ""))
    render_comedy_short(scenes)
    upload_to_youtube(kit)
