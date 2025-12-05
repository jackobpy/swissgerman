# Swiss German Lesson Lab

Single-page FastAPI app that lets you design a Swiss German lesson, generate six translation drills, and listen to Zurich-dialect audio from the provided TTS API.

## Running locally

1. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
2. Start the dev server (serves the API and static front-end):
   ```bash
   uvicorn main:app --reload --port 8000
   ```
3. Open the UI at http://localhost:8000

### Troubleshooting TTS SSL errors

Some environments report certificate or hostname errors when contacting the
Zurich TTS endpoint. To start the server without strict certificate checks,
disable verification before launching uvicorn:

```bash
export TTS_SSL_VERIFY=false
uvicorn main:app --reload --port 8000
```

If you host your own compatible TTS endpoint, override the target with
`TTS_BASE_URL`.

## Features
- Topic-driven lesson creation with optional Swiss German text to guide the generated sentences.
- Six quick exercises with Zurich-dialect prompts and reference translations.
- Prefetches TTS audio for the next exercise to keep the flow snappy.
- Simple, distraction-free layout inspired by Duolingo’s focus on practice.
