import asyncio
import difflib
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

import edge_tts
from google import genai
from google.genai import types
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from PIL import Image, ImageDraw, ImageFont

sys.stdout.reconfigure(line_buffering=True)

GEMINI_KEY = os.environ["GEMINI_API_KEY"]
TEXT_MODEL = os.getenv("GEMINI_TEXT_MODEL", "gemini-3.1-flash-lite")
IMAGE_MODEL = os.getenv("GEMINI_IMAGE_MODEL", "gemini-3.1-flash-image")
HISTORY_FILE = Path("used_scenarios.json")
OUTPUT_FILE = Path("final_short.mp4")
SCENE_COUNT = 5
HISTORY_LIMIT = 200

client = genai.Client(
    api_key=GEMINI_KEY,
    http_options=types.HttpOptions(timeout=180000),
)


def load_used_history():
    try:
        data = json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except (OSError, json.JSONDecodeError):
        return []


def save_used_history(history):
    HISTORY_FILE.write_text(
        json.dumps(history[-HISTORY_LIMIT:], ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def normalize(value):
    value = (value or "").lower()
    value = re.sub(r"[^\w\s]", " ", value, flags=re.UNICODE)
    return " ".join(value.split())


def similarity(left, right):
    a, b = normalize(left), normalize(right)
    if not a or not b:
        return 0.0
    sequence_score = difflib.SequenceMatcher(None, a, b).ratio()
    words_a, words_b = set(a.split()), set(b.split())
    overlap = len(words_a & words_b) / max(1, len(words_a | words_b))
    return max(sequence_score, overlap)


def validate_kit(kit):
    required = ("scenario_key", "title", "description", "characters", "dialogue", "scenes")
    if not isinstance(kit, dict) or any(not kit.get(key) for key in required):
        raise ValueError("Gemini returned an incomplete comedy kit.")
    if len(kit["scenes"]) != SCENE_COUNT:
        raise ValueError(f"Expected exactly {SCENE_COUNT} scenes.")
    if not isinstance(kit["dialogue"], list) or len(kit["dialogue"]) < 4:
        raise ValueError("The script needs at least four dialogue lines.")
    for scene in kit["scenes"]:
        if not scene.get("caption") or not scene.get("visual_prompt"):
            raise ValueError("Every scene needs a caption and visual prompt.")
    return kit


def generate_fresh_telugu_comedy_kit():
    history = load_used_history()
    recent = history[-HISTORY_LIMIT:]
    avoid = [
        {
            "scenario_key": item.get("scenario_key", ""),
            "script": item.get("script", ""),
        }
        for item in recent
    ]

    base_prompt = f"""
You are the head comedy writer for the Telugu YouTube Shorts channel "AI Navvula Adda".
Create ONE genuinely original, laugh-out-loud Telugu comedy skit for Indian/Telugu viewers.

ANTI-REPETITION IS ESSENTIAL:
Previously used scenario keys and scripts:
{json.dumps(avoid, ensure_ascii=False)}
Do not reuse the same premise, conflict, punchline, character situation, or merely change names.
Choose a fresh everyday premise that is not in the history. Rotate naturally among family,
friends, workplace, neighbours, school/college, village/town life, shopping, transport,
technology, food, festivals and social situations.

STORY RULES:
- Natural spoken Telugu, lively and contemporary; no formal/news Telugu.
- Start with a strong hook in the first spoken line.
- Build a clear setup, escalation and surprising final punchline.
- Total spoken dialogue: about 65-90 Telugu words.
- Use only 2 or 3 recurring characters in this skit.
- Characters must be ordinary adult Telugu people; keep clothing and appearance consistent.
- Dialogue speakers must match the character names.
- Five scenes, each with a clear visual action and comic beat.
- Image prompts must be detailed photorealistic live-action cinematic descriptions,
  vertical 9:16 framing, expressive faces, realistic Indian/Telugu locations and clothing.
- Do not ask the image model to render captions, subtitles, logos or readable text.
- Avoid stereotypes, political persuasion, real celebrities, copyrighted characters and cruelty.

Return valid JSON only with exactly these keys:
{{
  "scenario_key": "unique short English label for the specific premise",
  "title": "catchy Telugu title with #Shorts #AINavvulaAdda",
  "description": "short Telugu description and relevant hashtags",
  "characters": [
    {{"name":"name","look":"specific age range, face, hair, build, clothing and visual identity"}}
  ],
  "dialogue": [
    {{"speaker":"character name","text":"one spoken Telugu line"}}
  ],
  "scenes": [
    {{"caption":"short Telugu beat caption","visual_prompt":"photorealistic scene prompt in English, describing visible action and camera framing"}}
  ]
}}
There must be exactly five scene objects. Do not include markdown fences.
"""

    prompt = base_prompt
    models_to_try = [TEXT_MODEL, "gemini-3.1-flash-lite", "gemini-3.5-flash-lite", "gemini-3.8-flash"]
    deduped_models = []
    for m in models_to_try:
        if m and m not in deduped_models:
            deduped_models.append(m)

    last_error = None
    for attempt in range(6):
        model_name = deduped_models[min(attempt // 2, len(deduped_models) - 1)]
        print(f"[1/5] Writing a fresh Telugu comedy script with {model_name} (attempt {attempt + 1})...")
        try:
            response = client.models.generate_content(
                model=model_name,
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    temperature=1.0,
                ),
            )
            kit = validate_kit(json.loads(response.text))
            full_script = " ".join(line["text"].strip() for line in kit["dialogue"])
            candidate = f"{kit['scenario_key']} {full_script}"
            duplicate = False

            for old in recent:
                old_text = f"{old.get('scenario_key', '')} {old.get('script', '')}"
                if similarity(candidate, old_text) >= 0.72:
                    duplicate = True
                    break

            if duplicate:
                print("A similar premise was found in history; asking for a different story.")
                prompt += "\nIMPORTANT: Your previous attempt was too similar. Choose a completely different premise and punchline."
                continue

            kit["script"] = full_script
            fingerprint = hashlib.sha256(normalize(candidate).encode("utf-8")).hexdigest()
            history.append({
                "hash": fingerprint,
                "scenario_key": kit["scenario_key"],
                "script": full_script,
                "title": kit["title"],
            })
            save_used_history(history)
            return kit
        except Exception as error:
            last_error = error
            print(f"Script attempt {attempt + 1} ({model_name}) failed: {error}")
            time.sleep(6 if "429" in str(error) else 2)

    raise RuntimeError(f"Could not generate a sufficiently different comedy skit after six attempts: {last_error}")


def srt_timestamp(seconds):
    milliseconds = max(0, int(round(seconds * 1000)))
    hours, milliseconds = divmod(milliseconds, 3_600_000)
    minutes, milliseconds = divmod(milliseconds, 60_000)
    seconds_part, milliseconds = divmod(milliseconds, 1000)
    return f"{hours:02}:{minutes:02}:{seconds_part:02},{milliseconds:03}"


def media_duration(filename):
    result = subprocess.run(
        [
            "ffprobe", "-v", "error", "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1", str(filename),
        ],
        capture_output=True, text=True, check=True,
    )
    return float(result.stdout.strip())


async def generate_voice_and_subtitles(dialogue):
    print("[2/5] Creating Telugu character dialogue and timed subtitles...")
    voice_map = {"male": "te-IN-MohanNeural", "female": "te-IN-ShrutiNeural"}
    character_voice = {}
    audio_files = []
    subtitle_entries = []
    cursor = 0.0

    for index, line in enumerate(dialogue):
        speaker = line["speaker"].strip()
        voice = character_voice.setdefault(
            speaker,
            voice_map["male"] if len(character_voice) % 2 == 0 else voice_map["female"],
        )
        text = line["text"].strip()
        filename = Path(f"dialogue_{index:02}.mp3")
        communicate = edge_tts.Communicate(text, voice, rate="+5%", pitch="+1Hz")
        await communicate.save(str(filename))
        duration = media_duration(filename)
        audio_files.append(filename)
        subtitle_entries.append(
            f"{index + 1}\n{srt_timestamp(cursor)} --> {srt_timestamp(cursor + duration)}\n{text}\n"
        )
        cursor += duration
        time.sleep(0.15)

    concat_file = Path("audio_concat.txt")
    concat_file.write_text(
        "".join(f"file '{path.resolve()}'\n" for path in audio_files),
        encoding="utf-8",
    )
    subprocess.run(
        [
            "ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0",
            "-i", str(concat_file), "-c:a", "libmp3lame", "-q:a", "3", "voice.mp3",
        ],
        check=True,
    )
    Path("subs.srt").write_text("\n".join(subtitle_entries), encoding="utf-8")
    return media_duration("voice.mp3")


def _render_fallback_scene(filename: Path, index: int, caption: str):
    palettes = [
        ((24, 34, 79), (255, 193, 7), (255, 87, 34)),
        ((15, 76, 92), (0, 229, 255), (255, 214, 0)),
        ((74, 20, 140), (255, 64, 129), (255, 235, 59)),
        ((27, 94, 32), (178, 255, 89), (255, 171, 0)),
        ((106, 27, 154), (255, 110, 64), (0, 230, 118)),
    ]
    bg_top, accent_a, accent_b = palettes[index % len(palettes)]
    img = Image.new("RGB", (1080, 1920), bg_top)
    draw = ImageDraw.Draw(img)
    draw.polygon([(0, 0), (1080, 0), (1080, 500), (0, 720)], fill=accent_a)
    draw.polygon([(0, 1380), (1080, 1160), (1080, 1920), (0, 1920)], fill=accent_b)
    draw.ellipse([(240, 580), (840, 1180)], fill=(20, 24, 48), outline=(255, 255, 255), width=8)

    font = None
    for font_candidate in [
        "/usr/share/fonts/truetype/noto/NotoSansTelugu-Bold.ttf",
        "/usr/share/fonts/truetype/lohit-telugu/Lohit-Telugu.ttf",
        os.path.expanduser("~/.fonts/Lohit-Telugu.ttf"),
    ]:
        if os.path.exists(font_candidate):
            try:
                font = ImageFont.truetype(font_candidate, size=54)
                break
            except Exception:
                pass
    if font is None:
        font = ImageFont.load_default()

    words = caption.split()
    lines = []
    cur = ""
    for w in words:
        test = f"{cur} {w}".strip()
        bbox = draw.textbbox((0, 0), test, font=font)
        if (bbox[2] - bbox[0]) <= 500:
            cur = test
        else:
            if cur:
                lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)

    start_y = 880 - (len(lines) * 70) // 2
    for i, line in enumerate(lines):
        bbox = draw.textbbox((0, 0), line, font=font)
        x = (1080 - (bbox[2] - bbox[0])) // 2
        y = start_y + i * 70
        draw.text((x + 3, y + 3), line, fill=(0, 0, 0), font=font)
        draw.text((x, y), line, fill=(255, 255, 255), font=font)

    img.save(filename)


def generate_realistic_scenes(kit):
    print(f"[3/5] Generating {SCENE_COUNT} photorealistic Telugu comedy scenes...")
    character_bible = "\n".join(
        f"{character['name']}: {character['look']}" for character in kit["characters"]
    )
    images = []
    character_reference = None
    previous_scene = None

    for index, scene in enumerate(kit["scenes"]):
        filename = Path(f"scene_{index:02}.png")
        prompt = f"""
Create one photorealistic live-action cinematic frame for a Telugu comedy short.
IMPORTANT: Show the actual human characters as people, not icons, silhouettes,
illustrations, typography, abstract shapes, posters, or text-only graphics.
Vertical portrait 9:16 composition, realistic skin texture, expressive natural faces,
authentic South Indian/Telugu setting, cinematic lighting, detailed background.
Keep all recurring characters visually identical to the supplied reference image(s).
CHARACTER CONTINUITY GUIDE:
{character_bible}
SCENE {index + 1} OF {SCENE_COUNT}:
{scene['visual_prompt']}
The scene should communicate the comic action through facial expressions and body language.
No text, no captions, no watermark, no logos, no collage, no split panels.
"""
        contents = [prompt]
        if character_reference is not None:
            contents.append(character_reference)
        if previous_scene is not None and previous_scene is not character_reference:
            contents.append(previous_scene)

        last_error = None
        for attempt in range(2):
            try:
                response = client.models.generate_content(
                    model=IMAGE_MODEL,
                    contents=contents,
                    config=types.GenerateContentConfig(
                        response_modalities=["TEXT", "IMAGE"],
                        image_config=types.ImageConfig(aspect_ratio="9:16"),
                    ),
                )
                image_part = next(
                    (part for part in response.parts if getattr(part, "inline_data", None)),
                    None,
                )
                if image_part is None:
                    raise RuntimeError("Image model returned no image data.")
                image = image_part.as_image()
                image.save(filename)
                if character_reference is None:
                    character_reference = Image.open(filename).copy()
                previous_scene = Image.open(filename).copy()
                images.append(filename)
                print(f"Generated photorealistic human scene {index + 1}/{SCENE_COUNT}: {scene['caption']}")
                break
            except Exception as error:
                last_error = error
                error_text = str(error)
                print(f"Scene {index + 1} image attempt {attempt + 1} failed: {error_text}")
                if "429" in error_text or "RESOURCE_EXHAUSTED" in error_text or "quota" in error_text.lower():
                    raise RuntimeError(
                        "Gemini image generation quota is unavailable. No video was uploaded. "
                        "Enable billing for the Google Cloud project linked to GEMINI_API_KEY "
                        "and confirm that the selected image model has quota, then rerun."
                    ) from error
                if attempt == 0:
                    time.sleep(3)

        if len(images) != index + 1:
            raise RuntimeError(
                f"Could not generate real human-character artwork for scene {index + 1}: {last_error}"
            )

    if len(images) != SCENE_COUNT:
        raise RuntimeError(f"Expected {SCENE_COUNT} real generated images, got {len(images)}.")
    return images


def render_comedy_short(image_files, total_duration):
    print("[4/5] Rendering the vertical 1080x1920 Telugu comedy Short...")
    clip_duration = total_duration / len(image_files)
    frames_per_clip = max(1, round(clip_duration * 30))
    clip_paths = []

    for index, image_path in enumerate(image_files):
        clip_name = Path(f"clip_{index:02}.mp4")
        zoom_filter = (
            "scale=1080:1920:force_original_aspect_ratio=increase,"
            "crop=1080:1920,"
            f"zoompan=z='min(zoom+0.0012,1.12)':d={frames_per_clip}:"
            "s=1080x1920:fps=30,format=yuv420p"
        )
        subprocess.run(
            [
                "ffmpeg", "-y", "-loglevel", "error", "-loop", "1", "-i", str(image_path),
                "-vf", zoom_filter, "-t", f"{clip_duration:.3f}",
                "-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
                str(clip_name),
            ],
            check=True,
        )
        clip_paths.append(clip_name)

    Path("video_concat.txt").write_text(
        "".join(f"file '{path.resolve()}'\n" for path in clip_paths),
        encoding="utf-8",
    )
    subprocess.run(
        [
            "ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0",
            "-i", "video_concat.txt", "-c:v", "libx264", "-preset", "veryfast",
            "-crf", "20", "-pix_fmt", "yuv420p", "stitched_video.mp4",
        ],
        check=True,
    )

    font_dir = "/usr/share/fonts/truetype/noto"
    subtitle_style = (
        "FontName=Noto Sans Telugu,FontSize=20,PrimaryColour=&H00FFFFFF,"
        "OutlineColour=&H00101010,BackColour=&H80000000,BorderStyle=3,"
        "Outline=2,Shadow=1,Alignment=2,MarginV=170"
    )
    subtitle_filter = f"subtitles=subs.srt:fontsdir={font_dir}:force_style='{subtitle_style}'"
    subprocess.run(
        [
            "ffmpeg", "-y", "-loglevel", "error", "-i", "stitched_video.mp4",
            "-i", "voice.mp3", "-vf", subtitle_filter,
            "-map", "0:v:0", "-map", "1:a:0",
            "-c:v", "libx264", "-preset", "medium", "-crf", "19",
            "-c:a", "aac", "-b:a", "160k", "-shortest", str(OUTPUT_FILE),
        ],
        check=True,
    )
    if not OUTPUT_FILE.exists() or OUTPUT_FILE.stat().st_size < 100_000:
        raise RuntimeError("Rendered video is missing or unexpectedly small.")
    print(f"Rendered {OUTPUT_FILE} ({OUTPUT_FILE.stat().st_size:,} bytes).")


def upload_to_youtube(metadata):
    print("[5/5] Uploading the sample Telugu comedy Short to YouTube...")
    token_path = Path("token.json")
    if not token_path.exists():
        raise FileNotFoundError("token.json was not created; check YOUTUBE_TOKEN_JSON secret.")

    credentials = Credentials.from_authorized_user_file(
        str(token_path), ["https://www.googleapis.com/auth/youtube.upload"]
    )
    youtube = build("youtube", "v3", credentials=credentials, cache_discovery=False)
    body = {
        "snippet": {
            "title": metadata["title"][:100],
            "description": (
                f"{metadata['description']}\n\n"
                "#AINavvulaAdda #TeluguComedy #AIComedy #TeluguShorts #FunnyVideos"
            ),
            "tags": [
                "AINavvulaAdda", "TeluguComedy", "AIComedy", "TeluguShorts",
                "FunnyTelugu", "TeluguFunnyVideos", "Shorts",
            ],
            "categoryId": "23",
            "defaultLanguage": "te",
            "defaultAudioLanguage": "te",
        },
        "status": {
            "privacyStatus": os.getenv("YOUTUBE_PRIVACY_STATUS", "public"),
            "selfDeclaredMadeForKids": False,
        },
    }
    media = MediaFileUpload(str(OUTPUT_FILE), mimetype="video/mp4", chunksize=8 * 1024 * 1024, resumable=True)
    request = youtube.videos().insert(part="snippet,status", body=body, media_body=media)
    response = request.execute()
    print(f"YOUTUBE_UPLOAD_SUCCESS video_id={response['id']}")
    print(f"https://www.youtube.com/watch?v={response['id']}")


def main():
    kit = generate_fresh_telugu_comedy_kit()
    print(f"Today's premise: {kit['scenario_key']}")
    print(f"Title: {kit['title']}")
    total_duration = asyncio.run(generate_voice_and_subtitles(kit["dialogue"]))
    images = generate_realistic_scenes(kit)
    render_comedy_short(images, total_duration)
    upload_to_youtube(kit)


if __name__ == "__main__":
    main()
