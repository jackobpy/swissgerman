import base64
import mimetypes
from pathlib import Path
from typing import List, Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from gradio_client import Client

app = FastAPI(title="Swiss German Lesson Lab")
app.mount("/", StaticFiles(directory="static", html=True), name="static")


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

tts_client = Client("https://sttg4.fhm.ch/tts/")


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


def build_sentence(topic: str, book_text: Optional[str], idx: int) -> str:
    fragments = [
        "Du schaffsch das!",
        "Mir göh zäme Schritt für Schritt.",
        "Das isch e gueti Üebig für di.",
        "Probier s langsam und konzentriert.",
    ]
    topic_piece = topic.strip().capitalize()
    book_piece = ""
    if book_text:
        lines = [line.strip() for line in book_text.splitlines() if line.strip()]
        if lines:
            book_piece = lines[idx % len(lines)][:120]
    additive = f" {book_piece}" if book_piece else ""
    encouragement = fragments[idx % len(fragments)]
    return f"{topic_piece}: {encouragement}{additive}"


def generate_exercises(request: LessonRequest) -> List[Exercise]:
    exercises: List[Exercise] = []
    for idx in range(6):
        swiss_sentence = build_sentence(request.topic, request.book_text, idx)
        exercises.append(
            Exercise(
                id=idx + 1,
                swiss_sentence=swiss_sentence,
                translation_hint="Translate this Zurich dialect sentence into English.",
                reference_translation=f"{request.topic.strip().capitalize()} practice line {idx + 1}.",
            )
        )
    return exercises


@app.post("/api/lesson", response_model=LessonResponse)
async def create_lesson(request: LessonRequest) -> LessonResponse:
    normalized_dialect = request.dialect if request.dialect in dialect_choices else "Zürich"
    exercises = generate_exercises(request)
    return LessonResponse(topic=request.topic, dialect=normalized_dialect, exercises=exercises)


def encode_audio_file(audio_path: Path) -> AudioResponse:
    mime_type, _ = mimetypes.guess_type(str(audio_path))
    mime_type = mime_type or "audio/wav"
    binary = audio_path.read_bytes()
    encoded = base64.b64encode(binary).decode("utf-8")
    return AudioResponse(audio_base64=encoded, content_type=mime_type)


@app.post("/api/audio", response_model=AudioResponse)
async def fetch_audio(request: AudioRequest) -> JSONResponse:
    try:
        result = tts_client.predict(
            request.text,
            request.dialect,
            api_name="speech_interface",
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"TTS service failed: {exc}") from exc

    audio_path: Optional[Path] = None
    if isinstance(result, (list, tuple)) and result:
        first = result[0]
        if isinstance(first, str):
            audio_path = Path(first)
    elif isinstance(result, str):
        audio_path = Path(result)

    if not audio_path or not audio_path.exists():
        raise HTTPException(status_code=500, detail="Unexpected response from TTS service")

    response = encode_audio_file(audio_path)
    return JSONResponse(content=response.model_dump())
