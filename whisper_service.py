"""Whisper validation micro-service for Bray Music Studio.

Runs on the host (ROG-STRIX) at port 7862. Uses faster-whisper medium/int8/CPU
to analyze vocal quality in generated audio tracks.

Install: pip install fastapi uvicorn faster-whisper
Run: uvicorn whisper_service:app --host 0.0.0.0 --port 7862
"""

import logging
from pathlib import Path

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Whisper Validation Service")

# Lazy-load model on first request
_model = None
AUDIO_DIR = Path("/home/bobray/ace-step/outputs/api_audio")


def _get_model():
    global _model
    if _model is None:
        from faster_whisper import WhisperModel
        logger.info("Loading faster-whisper medium model (int8, CPU)...")
        _model = WhisperModel("medium", device="cpu", compute_type="int8")
        logger.info("Model loaded.")
    return _model


class ValidateRequest(BaseModel):
    filename: str


class ValidateResponse(BaseModel):
    quality_score: float
    quality_rating: str
    segments: int
    good_segments: int
    avg_logprob: float


@app.post("/validate", response_model=ValidateResponse)
async def validate(req: ValidateRequest):
    audio_path = AUDIO_DIR / req.filename
    if not audio_path.exists():
        raise HTTPException(status_code=404, detail=f"Audio file not found: {req.filename}")

    model = _get_model()

    segments_list, info = model.transcribe(
        str(audio_path),
        vad_filter=True,
        vad_parameters={"min_silence_duration_ms": 500},
    )

    total = 0
    good = 0
    logprob_sum = 0.0

    for seg in segments_list:
        total += 1
        logprob_sum += seg.avg_logprob
        if seg.avg_logprob > -0.8 and seg.no_speech_prob < 0.5:
            good += 1

    if total == 0:
        return ValidateResponse(
            quality_score=0.0,
            quality_rating="NONE",
            segments=0,
            good_segments=0,
            avg_logprob=0.0,
        )

    good_pct = good / total
    avg_lp = logprob_sum / total

    if good_pct >= 0.8 and avg_lp > -0.6:
        rating = "GREAT"
    elif good_pct >= 0.6 and avg_lp > -0.8:
        rating = "GOOD"
    elif good_pct >= 0.4:
        rating = "FAIR"
    else:
        rating = "POOR"

    logger.info(
        "Validated %s: %d/%d good segments (%.0f%%), avg_logprob=%.2f → %s",
        req.filename, good, total, good_pct * 100, avg_lp, rating,
    )

    return ValidateResponse(
        quality_score=round(good_pct, 3),
        quality_rating=rating,
        segments=total,
        good_segments=good,
        avg_logprob=round(avg_lp, 3),
    )


@app.get("/health")
async def health():
    return {"status": "ok", "model_loaded": _model is not None}
