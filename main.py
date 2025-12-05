import base64
import json
import logging
import math
import mimetypes
import os
import wave
from functools import lru_cache
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Dict, List, Optional, Tuple

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from gradio_client import Client
from openai import OpenAI

logger = logging.getLogger(__name__)

app = FastAPI(title="Swiss German Lesson Lab")
app.mount("/static", StaticFiles(directory="static"), name="static")


dialect_choices = [
    "Aarau",
    "Bern",
    "Basel",
    "Graubünden",
    "Luzern",
    "St. Gallen",
    "Valais",
    "Zürich",
]


def _is_truthy_env(var_name: str, default: str = "true") -> bool:
    raw = os.getenv(var_name, default)
    return str(raw).strip().lower() not in {"0", "false", "no", "off", ""}


def _openai_client() -> OpenAI:
    return OpenAI()


@lru_cache(maxsize=1)
def get_tts_client() -> Client:
    """Construct a Gradio client, optionally relaxing SSL verification.

    Some environments surface certificate/hostname issues with the hosted Zurich
    dialect TTS service. When TTS_SSL_VERIFY=false, SSL verification is turned
    off. If verification is enabled and instantiation fails, we retry with
    verification disabled so the app can still start.
    """

    base_url = os.getenv("TTS_BASE_URL", "https://sttg4.fhm.ch/tts/")
    verify_ssl = _is_truthy_env("TTS_SSL_VERIFY", "true")

    try:
        return Client(base_url, ssl_verify=verify_ssl)
    except Exception:
        if verify_ssl:
            # Fallback to avoid startup crashes when cert validation fails.
            try:
                return Client(base_url, ssl_verify=False)
            except Exception as exc:  # noqa: BLE001
                raise RuntimeError(
                    "Could not initialize TTS client even after disabling SSL verification."
                ) from exc
        raise


class LessonRequest(BaseModel):
    topic: str = Field(..., min_length=3, description="What you want to practice")
    dialect: str = Field("Zürich", description="Swiss German dialect for pronunciation")
    book_text: Optional[str] = Field(
        default=None,
        description="Optional Swiss German reference text the LLM can draw from.",
    )


class Exercise(BaseModel):
    id: int
    swiss_sentence: str
    translation_hint: str
    reference_translation: str


class LessonResponse(BaseModel):
    topic: str
    dialect: str
    exercises: List[Exercise]


class AudioRequest(BaseModel):
    text: str
    dialect: str = "Zürich"


class AudioResponse(BaseModel):
    audio_base64: str
    content_type: str


def _build_generation_prompt(topic: str, book_text: Optional[str]) -> str:
    sample_text = ""
    if book_text:
        stripped = [line.strip() for line in book_text.splitlines() if line.strip()]
        if stripped:
            sample_text = "\n\nOptional reference (Swiss German):\n" + "\n".join(
                stripped[:6]
            )

    return (
        "You are a friendly Swiss German language app. "
        "Write 6 short sentences in Züridütsch (Zürich dialect) about the given topic. "
        "Each sentence must be about the topic and written fully in Swiss German (no labels). "
        "Also provide a clear English translation for each sentence. "
        "Return a JSON array of objects with keys 'swiss_sentence' and 'reference_translation'.\n\n"
        f"Topic: {topic.strip() or 'Alltag'}" + sample_text
    )


@lru_cache(maxsize=24)
def _generate_sentence_batch(topic: str, book_text: Optional[str]) -> List[Dict[str, str]]:
    client = _openai_client()
    model = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")
    prompt = _build_generation_prompt(topic, book_text)

    response = client.chat.completions.create(
        model=model,
        temperature=0.6,
        messages=[
            {"role": "system", "content": "You are concise and stay on topic."},
            {"role": "user", "content": prompt},
        ],
    )
    content = response.choices[0].message.content if response.choices else "[]"

    try:
        payload = json.loads(content or "[]")
        if isinstance(payload, list):
            normalized: List[Dict[str, str]] = []
            for entry in payload:
                if not isinstance(entry, dict):
                    continue
                swiss_sentence = str(entry.get("swiss_sentence", "")).strip()
                reference_translation = str(entry.get("reference_translation", "")).strip()
                if swiss_sentence and reference_translation:
                    normalized.append(
                        {
                            "swiss_sentence": swiss_sentence,
                            "reference_translation": reference_translation,
                        }
                    )
            if normalized:
                return normalized
    except Exception:  # noqa: BLE001
        logger.warning("Unable to parse LLM sentence batch; falling back to empty list.")

    return []


def build_sentence(topic: str, book_text: Optional[str], idx: int) -> Tuple[str, str]:
    batch = _generate_sentence_batch(topic, book_text)
    if idx < len(batch):
        entry = batch[idx]
        return entry["swiss_sentence"], entry["reference_translation"]

    topic_piece = topic.strip() or "dini Idee"
    return (
        f"Mir bruuche meh Infos zum Thema {topic_piece}, drum probier s Sätzli nomol.",
        "Need more topic details to generate a sentence.",
    )


def generate_exercises(request: LessonRequest, dialect: str) -> List[Exercise]:
    exercises: List[Exercise] = []
    for idx in range(6):
        swiss_sentence, english_reference = build_sentence(request.topic, request.book_text, idx)
        exercises.append(
            Exercise(
                id=idx + 1,
                swiss_sentence=swiss_sentence,
                translation_hint=f"Translate this {dialect} dialect sentence into English.",
                reference_translation=english_reference,
            )
        )
    return exercises


@app.post("/api/lesson", response_model=LessonResponse)
async def create_lesson(request: LessonRequest) -> LessonResponse:
    normalized_dialect = request.dialect if request.dialect in dialect_choices else "Zürich"
    exercises = generate_exercises(request, normalized_dialect)
    return LessonResponse(topic=request.topic, dialect=normalized_dialect, exercises=exercises)

@app.get("/", include_in_schema=False)
async def serve_index() -> FileResponse:
    return FileResponse(Path("static/index.html"))


def encode_audio_file(audio_path: Path) -> AudioResponse:
    mime_type, _ = mimetypes.guess_type(str(audio_path))
    mime_type = mime_type or "audio/wav"
    binary = audio_path.read_bytes()
    encoded = base64.b64encode(binary).decode("utf-8")
    return AudioResponse(audio_base64=encoded, content_type=mime_type)


def synthesize_placeholder_audio(text: str) -> Path:
    """Create a short WAV tone as a fallback when TTS is unavailable."""

    duration_seconds = min(3.5, 0.5 + len(text) / 25)
    sample_rate = 22050
    amplitude = 0.3
    base_freq = 440.0
    wobble = 60.0

    with NamedTemporaryFile(delete=False, suffix=".wav") as tmp:
        with wave.open(tmp, "w") as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(sample_rate)

            frames = []
            total_frames = int(duration_seconds * sample_rate)
            for i in range(total_frames):
                freq = base_freq + wobble * math.sin(2 * math.pi * i / sample_rate)
                sample = amplitude * math.sin(2 * math.pi * freq * i / sample_rate)
                frames.append(int(sample * 32767))

            wav_file.writeframes(b"".join(int(frame).to_bytes(2, "little", signed=True) for frame in frames))

        return Path(tmp.name)


@app.post("/api/audio", response_model=AudioResponse)
async def fetch_audio(request: AudioRequest) -> JSONResponse:
    tts_client: Optional[Client] = None
    try:
        tts_client = get_tts_client()
    except Exception as exc:  # noqa: BLE001
        logger.warning("TTS client unavailable, falling back to synth tone: %s", exc)

    audio_path: Optional[Path] = None
    if tts_client:
        try:
            result = tts_client.predict(
                request.text,
                request.dialect if request.dialect in dialect_choices else "Zürich",
                api_name="speech_interface",
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("TTS request failed, using fallback audio: %s", exc)
            result = None

        if isinstance(result, (list, tuple)) and result:
            first = result[0]
            if isinstance(first, str):
                audio_path = Path(first)
        elif isinstance(result, str):
            audio_path = Path(result)

    if not audio_path or not audio_path.exists():
        audio_path = synthesize_placeholder_audio(request.text)

    response = encode_audio_file(audio_path)

    try:
        if audio_path.exists() and audio_path.name.startswith("tmp"):
            audio_path.unlink(missing_ok=True)
    finally:
        return JSONResponse(content=response.model_dump())
