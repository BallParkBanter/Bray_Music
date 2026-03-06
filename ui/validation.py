"""HTTP client for the Whisper validation micro-service."""

import logging

import httpx

from config import WHISPER_URL

logger = logging.getLogger(__name__)


async def validate_track(filename: str) -> dict | None:
    """Call the whisper service to validate a track's vocal quality.

    Returns dict with keys: quality_score (float), quality_rating (str),
    segments (int), good_segments (int), avg_logprob (float).
    Returns None if the service is unavailable or validation fails.
    """
    try:
        async with httpx.AsyncClient(timeout=300) as client:
            r = await client.post(
                f"{WHISPER_URL}/validate",
                json={"filename": filename},
            )
            if r.status_code == 200:
                data = r.json()
                logger.info(
                    "Whisper validation: %s — %s (%.0f%% good)",
                    filename,
                    data.get("quality_rating", "?"),
                    (data.get("quality_score", 0) or 0) * 100,
                )
                return data
            logger.warning("Whisper service returned %d: %s", r.status_code, r.text)
    except httpx.ConnectError:
        logger.warning("Whisper service not available at %s", WHISPER_URL)
    except Exception as e:
        logger.warning("Whisper validation failed: %s", e)
    return None
