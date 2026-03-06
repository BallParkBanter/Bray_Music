"""Generate song lyrics from a description using Ollama LLM.

Called by the generation pipeline when Simple mode requests vocals
but no lyrics are provided. Uses Ollama on Optimus (192.168.1.145)
to avoid GPU contention with ACE-Step on ROG-STRIX.
"""

import logging
import httpx
from config import OLLAMA_URL

logger = logging.getLogger(__name__)

LYRICS_PROMPT_DEFAULT = """You are a professional songwriter. Given a song description, write complete song lyrics for a full-length 4-minute song.

Structure (follow this exactly):
[Intro] - 2 lines setting the mood
[Verse 1] - 6 lines
[Chorus] - 4 lines (the hook, most memorable part)
[Verse 2] - 6 lines (advance the story)
[Chorus] - repeat the same chorus
[Verse 3] - 6 lines (emotional climax or resolution)
[Bridge] - 4 lines (different melody/perspective, builds tension)
[Chorus] - repeat the chorus one final time
[Outro] - 2 lines wrapping up

Rules:
- The chorus MUST repeat identically each time
- Each line should be short enough to sing (under 12 words)
- Lyrics must match the described mood, genre, and story
- Write vivid, specific imagery — no generic filler
- Output ONLY the lyrics with structure tags. No commentary.

Song description: {description}

Lyrics:"""

LYRICS_PROMPT_RAP = """You are an elite rap songwriter and battle MC. Given a song description, write complete rap lyrics for a full-length 4-minute track.

Structure (follow this exactly):
[Intro] - 4 bars setting the tone
[Verse 1] - 16 bars with tight rhyme schemes, internal rhymes, and wordplay
[Hook] - 4 bars (the catchy repeated refrain)
[Verse 2] - 16 bars (escalate the energy, new angle on the topic)
[Hook] - repeat the same hook
[Verse 3] - 16 bars (hardest bars, punchlines, mic-drop moments)
[Bridge] - 8 bars (switch up the flow, build tension)
[Hook] - repeat the hook one final time
[Outro] - 4 bars wrapping up

Rules:
- Every bar MUST rhyme — use multisyllabic rhymes, internal rhymes, and slant rhymes
- Pack in wordplay, metaphors, similes, and punchlines
- The hook MUST repeat identically each time
- Vary the flow — mix fast bars with slower emphatic lines
- Write with confidence and swagger appropriate to the topic
- Output ONLY the lyrics with structure tags. No commentary.

Song description: {description}

Lyrics:"""

LYRICS_PROMPT_BALLAD = """You are a professional songwriter specializing in emotional ballads. Given a song description, write complete lyrics for a moving 4-minute ballad.

Structure (follow this exactly):
[Intro] - 2 lines, gentle and evocative
[Verse 1] - 8 lines, tell the story with intimate detail
[Chorus] - 6 lines (emotional peak, singable and memorable)
[Verse 2] - 8 lines (deepen the emotion, reveal more)
[Chorus] - repeat the same chorus
[Bridge] - 6 lines (vulnerable moment, key change feel)
[Chorus] - repeat the chorus with full power
[Outro] - 4 lines, quiet resolution

Rules:
- The chorus MUST repeat identically each time
- Use sensory details — sounds, textures, scents, light
- Build emotional arc from tender to powerful and back
- Each line should flow naturally when sung slowly
- Output ONLY the lyrics with structure tags. No commentary.

Song description: {description}

Lyrics:"""

_GENRE_PROMPT_MAP = {
    "hip hop": LYRICS_PROMPT_RAP,
    "ballad": LYRICS_PROMPT_BALLAD,
    "gospel": LYRICS_PROMPT_BALLAD,
}

TITLE_PROMPT = """You are a music industry expert. Given a song description, create a short, catchy song title.

Rules:
- 1-5 words maximum
- Creative and evocative, like a real song title
- No quotes, no punctuation, no explanation
- Just output the title, nothing else

Song description: {description}

Title:"""

TIMEOUT = 90.0  # seconds — lyrics gen should be fast
MODEL_LOAD_TIME = 25.0  # seconds — cold start to load gemma3:12b into GPU


async def _is_model_loaded(client: httpx.AsyncClient, model: str) -> bool:
    """Check /api/ps to see if model is currently in GPU memory."""
    try:
        resp = await client.get(f"{OLLAMA_URL}/api/ps", timeout=5.0)
        if resp.status_code == 200:
            for m in resp.json().get("models", []):
                if model in m["name"]:
                    return True
    except Exception:
        pass
    return False


async def ensure_model_loaded(model: str = "gemma3:12b") -> bool:
    """Check if model is in GPU memory; if not, load it and verify.

    Returns True if model had to be loaded (cold start), False if already warm.
    """
    try:
        async with httpx.AsyncClient(timeout=MODEL_LOAD_TIME + 15) as client:
            if await _is_model_loaded(client, model):
                logger.info(f"Ollama model {model} already loaded in GPU")
                return False

            # Model not loaded — trigger a load with minimal prompt
            logger.info(f"Ollama model {model} not in GPU, pre-loading...")
            await client.post(
                f"{OLLAMA_URL}/api/generate",
                json={"model": model, "prompt": "", "stream": False, "keep_alive": "10m"},
            )

            # Verify the model is now loaded
            if await _is_model_loaded(client, model):
                logger.info(f"Ollama model {model} loaded into GPU (verified)")
            else:
                logger.warning(f"Ollama model {model} load returned OK but not showing in /api/ps")
            return True
    except Exception as e:
        logger.warning(f"Model pre-load failed: {e} — will retry on actual call")
        return True


async def generate_lyrics(description: str, genre: str = "", model: str = "gemma3:12b") -> str | None:
    """Generate song lyrics from a description via Ollama.

    Returns structured lyrics string, or None on failure.
    """
    if not description or not description.strip():
        return None

    await ensure_model_loaded(model)

    template = _GENRE_PROMPT_MAP.get(genre, LYRICS_PROMPT_DEFAULT)
    prompt = template.format(description=description)

    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            resp = await client.post(
                f"{OLLAMA_URL}/api/generate",
                json={
                    "model": model,
                    "prompt": prompt,
                    "stream": False,
                    "think": False,
                    "options": {
                        "temperature": 0.8,
                        "top_p": 0.9,
                        "num_predict": 2048,
                        "num_gpu": 99,
                        "num_ctx": 4096,
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


async def generate_title(description: str, model: str = "gemma3:12b") -> str | None:
    """Generate a short song title from a description via Ollama.

    Returns a title string, or None on failure.
    """
    if not description or not description.strip():
        return None

    await ensure_model_loaded(model)

    prompt = TITLE_PROMPT.format(description=description)

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(
                f"{OLLAMA_URL}/api/generate",
                json={
                    "model": model,
                    "prompt": prompt,
                    "stream": False,
                    "think": False,
                    "options": {
                        "temperature": 0.9,
                        "num_predict": 30,
                        "num_gpu": 99,
                        "num_ctx": 2048,
                    },
                },
            )
            resp.raise_for_status()
            data = resp.json()
            title = data.get("response", "").strip()

            # Strip any <think>...</think> blocks (qwen3 reasoning)
            import re
            title = re.sub(r'<think>.*?</think>', '', title, flags=re.DOTALL).strip()

            # Clean up: remove quotes, limit length
            title = title.strip('"\'').strip()
            if title and len(title) > 1:
                # Take only first line if multi-line
                title = title.split('\n')[0].strip()
                if len(title) > 60:
                    title = title[:60]
                logger.info(f"Generated title: '{title}'")
                return title
            return None

    except Exception as e:
        logger.warning(f"Title generation failed: {e}")
        return None
