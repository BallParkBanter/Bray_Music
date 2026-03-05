"""Generate song lyrics from a description using Ollama LLM.

Called by the generation pipeline when Simple mode requests vocals
but no lyrics are provided. Uses Ollama on Optimus (192.168.1.145)
to avoid GPU contention with ACE-Step on ROG-STRIX.
"""

import logging
import httpx
from config import OLLAMA_URL

logger = logging.getLogger(__name__)

LYRICS_PROMPT = """You are a professional songwriter. Given a song description, write complete song lyrics for a full-length song.

Structure (follow this exactly):
[Intro] - 2 lines setting the mood
[Verse 1] - 4 lines
[Chorus] - 4 lines (the hook, most memorable part)
[Verse 2] - 4 lines (advance the story)
[Chorus] - repeat the same chorus
[Verse 3] - 4 lines (emotional climax or resolution)
[Bridge] - 4 lines (different melody/perspective, builds tension)
[Chorus] - repeat the chorus one final time
[Outro] - 2 lines wrapping up

Rules:
- The chorus MUST repeat identically after every verse
- Each line should be short enough to sing (under 12 words)
- Lyrics must match the described mood, genre, and story
- Write vivid, specific imagery — no generic filler
- Output ONLY the lyrics with structure tags. No commentary.

Song description: {description}

Lyrics:"""

TIMEOUT = 90.0  # seconds — lyrics gen should be fast


async def generate_lyrics(description: str, model: str = "qwen3:4b") -> str | None:
    """Generate song lyrics from a description via Ollama.

    Returns structured lyrics string, or None on failure.
    """
    if not description or not description.strip():
        return None

    prompt = LYRICS_PROMPT.format(description=description)

    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            resp = await client.post(
                f"{OLLAMA_URL}/api/generate",
                json={
                    "model": model,
                    "prompt": prompt,
                    "stream": False,
                    "options": {
                        "temperature": 0.8,
                        "top_p": 0.9,
                        "num_predict": 1024,
                    },
                },
            )
            resp.raise_for_status()
            data = resp.json()
            lyrics = data.get("response", "").strip()

            # Strip any <think>...</think> blocks (qwen3 reasoning)
            import re
            lyrics = re.sub(r'<think>.*?</think>', '', lyrics, flags=re.DOTALL).strip()

            if lyrics and len(lyrics) > 20:
                logger.info(f"Generated lyrics ({len(lyrics)} chars) from description")
                return lyrics
            else:
                logger.warning(f"Lyrics too short or empty: {lyrics[:50]}")
                return None

    except httpx.TimeoutException:
        logger.warning("Ollama lyrics generation timed out")
        return None
    except Exception as e:
        logger.error(f"Ollama lyrics generation failed: {e}")
        return None
