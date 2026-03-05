import asyncio
import json
import random
import shutil
from pathlib import Path

import httpx

from models import GenerateRequest
from config import ACESTEP_URL, AUDIO_DIR

TIMEOUT = 600.0  # 10 min — FP32 on Pascal is slower

# The /gradio_api/info reports 50 named params (indices 0-49).
# But the actual handler has 55 inputs: a hidden State at real position 37,
# and 4 more States at positions 51-54.
#
# API index -> real position mapping:
#   API 0-36  -> real 0-36  (no shift)
#   (hidden)  -> real 37    (State, must be None)
#   API 37-49 -> real 38-50 (shifted +1)
#   (hidden)  -> real 51-54 (States, must be None)

REAL_PARAM_COUNT = 55
STATE_INJECTION = 37  # hidden State component is here

# Defaults by API index (from /gradio_api/info)
API_DEFAULTS = {
    0: "",              # Music Caption
    1: "",              # Lyrics
    2: None,            # BPM
    3: "",              # Key
    4: "",              # Time Signature
    5: "unknown",       # Vocal Language
    6: 32,              # DiT Inference Steps
    7: 7.0,             # DiT Guidance Scale
    8: True,            # Random Seed
    9: "-1",            # Seed
    10: None,           # Reference Audio
    11: -1,             # Audio Duration
    12: 2,              # Batch Size
    13: None,           # Source Audio
    14: None,           # LM Codes Hints
    15: 0.0,            # Repainting Start
    16: -1,             # Repainting End
    17: "Fill the audio semantic mask based on the given conditions:",
    18: 1.0,            # LM Codes Strength
    19: 0.0,            # Cover Strength
    20: "text2music",   # task_type
    21: False,          # Use ADG
    22: 0.0,            # CFG Interval Start
    23: 1.0,            # CFG Interval End
    24: 3.0,            # Shift
    25: "ode",          # Inference Method
    26: "",             # Custom Timesteps
    27: "mp3",          # Audio Format
    28: 0.85,           # LM Temperature
    29: True,           # Think
    30: 2.0,            # LM CFG Scale
    31: 0,              # LM Top-K
    32: 0.9,            # LM Top-P
    33: "NO USER INPUT",  # LM Negative Prompt
    34: True,           # CoT Metas
    35: False,          # CaptionRewrite
    36: True,           # CoT Language
    37: False,          # Constrained Decoding Debug
    38: True,           # ParallelThinking
    39: False,          # Auto Score
    40: False,          # Auto LRC
    41: 0.5,            # Quality Score Sensitivity
    42: 8,              # LM Batch Chunk Size
    43: None,           # Track Name
    44: [],             # Track Names
    45: True,           # Enable Normalization
    46: -1.0,           # Target Peak dB
    47: 0.0,            # Latent Shift
    48: 1.0,            # Latent Rescale
    49: False,          # AutoGen
}


def _api_to_real(api_params: dict) -> list:
    """Convert API-indexed params dict to real 55-element array with State injection."""
    real = [None] * REAL_PARAM_COUNT
    for api_idx in range(50):
        val = api_params.get(api_idx, API_DEFAULTS.get(api_idx))
        if api_idx < STATE_INJECTION:
            real[api_idx] = val
        else:
            real[api_idx + 1] = val  # shift by 1 past the State
    # Position 37 = State (None), positions 51-54 = States (None) -- already None
    return real


def _build_params(req: GenerateRequest) -> tuple[list, int]:
    """Build the 55-element parameter array for ACE-Step Gradio API."""
    api = dict(API_DEFAULTS)

    api[0] = req.description

    # Instrumental mode: replace lyrics with [Instrumental] tag
    if not req.include_vocals:
        api[1] = "[Instrumental]"
    else:
        api[1] = req.lyrics or ""

    if req.bpm and req.bpm.strip():
        try:
            api[2] = float(req.bpm)
        except ValueError:
            pass
    if req.key and req.key.strip():
        api[3] = req.key
    api[5] = "en"
    api[6] = 8               # turbo model inference steps

    # Creativity: 0 (strict) → guidance 10, 100 (free) → guidance 1.5
    api[7] = 10.0 - (req.creativity / 100.0) * 8.5

    api[11] = -1 if req.duration == 0 else req.duration * 60  # 0 = auto duration
    api[12] = 1               # batch size 1
    api[27] = "flac"

    # CaptionRewrite: enhance caption text (does NOT generate lyrics).
    # Only enable when user explicitly requests enhancement.
    if req.enhance_lyrics:
        api[35] = True         # CaptionRewrite

    # Seed
    if req.seed.strip().lstrip("-").isdigit():
        seed_val = int(req.seed)
        api[8] = False
    else:
        seed_val = random.randint(0, 2**31)
        api[8] = True
    api[9] = str(seed_val)

    return _api_to_real(api), seed_val


def _extract_flac_path(data: list) -> str | None:
    """Extract FLAC file path from Gradio SSE response data array.

    The response format varies between generating/complete events.
    FLAC info can appear as:
      - data[0].value.path  (generating event with playback)
      - data[8][0].path     (file list in complete event)
      - Any dict with 'path' ending in .flac anywhere in the array
    """
    # Strategy 1: Check data[8] — the file list position
    if len(data) > 8 and isinstance(data[8], list):
        for item in data[8]:
            if isinstance(item, dict) and item.get("path", "").endswith(".flac"):
                return item["path"]

    # Strategy 2: Check data[0].value.path (generating event)
    if data and isinstance(data[0], dict):
        val = data[0].get("value")
        if isinstance(val, dict) and val.get("path", "").endswith(".flac"):
            return val["path"]

    # Strategy 3: Scan all items for any dict with a .flac path
    for item in data:
        if isinstance(item, dict) and item.get("path", "").endswith(".flac"):
            return item["path"]
        if isinstance(item, list):
            for sub in item:
                if isinstance(sub, dict) and sub.get("path", "").endswith(".flac"):
                    return sub["path"]
    return None


def _check_for_error(data: list) -> str | None:
    """Check if the response data contains an error message."""
    for item in data:
        if isinstance(item, str) and item.startswith("Error:"):
            return item
    return None


async def generate(req: GenerateRequest) -> dict:
    """Submit generation request, poll until complete, download FLAC to shared volume."""
    param_array, seed_used = _build_params(req)

    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        # Submit
        resp = await client.post(
            f"{ACESTEP_URL}/gradio_api/call/generation_wrapper",
            json={"data": param_array},
        )
        resp.raise_for_status()
        event_id = resp.json()["event_id"]

        # Poll SSE stream
        gradio_path = await _poll_result(client, event_id)

        # Download FLAC from Gradio file serving to our shared volume
        filename = Path(gradio_path).name
        local_path = AUDIO_DIR / filename
        await _download_file(client, gradio_path, local_path)

    return {"file_path": str(local_path), "filename": filename, "seed": seed_used}


async def _poll_result(client: httpx.AsyncClient, event_id: str) -> str:
    """Read SSE stream until complete, return Gradio file path."""
    url = f"{ACESTEP_URL}/gradio_api/call/generation_wrapper/{event_id}"

    async with client.stream("GET", url, timeout=TIMEOUT) as response:
        response.raise_for_status()
        event_type = None
        async for line in response.aiter_lines():
            line = line.strip()
            if not line:
                continue
            if line.startswith("event:"):
                event_type = line.split(":", 1)[1].strip()
            elif line.startswith("data:"):
                data_str = line.split(":", 1)[1].strip()
                if data_str == "null":
                    continue

                if event_type == "error":
                    raise RuntimeError(f"ACE-Step error: {data_str}")

                if event_type in ("complete", "generating"):
                    try:
                        data = json.loads(data_str)
                    except json.JSONDecodeError:
                        continue

                    # Check for error messages in the response
                    err = _check_for_error(data)
                    if err:
                        raise RuntimeError(f"ACE-Step generation error: {err}")

                    # Extract FLAC path
                    if event_type == "complete":
                        path = _extract_flac_path(data)
                        if path:
                            return path
                        raise RuntimeError(f"No FLAC file in complete event: {data_str[:300]}")

    raise RuntimeError("SSE stream ended without completion event")


async def _download_file(client: httpx.AsyncClient, gradio_path: str, local_path: Path) -> None:
    """Download file from Gradio's file serving endpoint to local path."""
    local_path.parent.mkdir(parents=True, exist_ok=True)
    file_url = f"{ACESTEP_URL}/gradio_api/file={gradio_path}"
    resp = await client.get(file_url, timeout=60.0)
    resp.raise_for_status()
    local_path.write_bytes(resp.content)


def _extract_progress_message(data) -> str | None:
    """Try to extract a human-readable progress message from Gradio generating event data."""
    if not isinstance(data, list):
        return None

    for item in data:
        if isinstance(item, dict):
            # Gradio 4+/6+ progress_data format
            pd = item.get("progress_data")
            if isinstance(pd, list) and pd:
                p = pd[0]
                desc = p.get("desc", "")
                progress = p.get("progress")
                length = p.get("length")
                if desc and progress is not None and length:
                    pct = int(progress / length * 100) if length else 0
                    return f"{desc}: {pct}%"
                elif desc:
                    return desc
        elif isinstance(item, str) and item and not item.startswith("Error"):
            # Some implementations put progress text as a string
            return item
    return None


async def generate_streaming(req: GenerateRequest):
    """Async generator yielding real-time progress events during generation.

    Events:
        {"event":"step", "step":"submit|queue|generate|decode|save", "state":"active|done"}
        {"event":"progress", "message":"..."}
        {"event":"complete", "result":{"file_path":..., "filename":..., "seed":...}}
        {"event":"error", "message":"..."}
    """
    param_array, seed_used = _build_params(req)

    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        # Step 1: Submit to ACE-Step
        try:
            resp = await client.post(
                f"{ACESTEP_URL}/gradio_api/call/generation_wrapper",
                json={"data": param_array},
            )
            resp.raise_for_status()
            event_id = resp.json()["event_id"]
        except Exception as e:
            yield {"event": "error", "message": f"Submit failed: {e}"}
            return

        yield {"event": "step", "step": "submit", "state": "done"}
        yield {"event": "step", "step": "queue", "state": "active"}

        # Step 2-5: Poll SSE stream from ACE-Step
        url = f"{ACESTEP_URL}/gradio_api/call/generation_wrapper/{event_id}"
        flac_path = None
        entered_generating = False

        try:
            async with client.stream("GET", url, timeout=TIMEOUT) as response:
                response.raise_for_status()

                event_type = None
                async for line in response.aiter_lines():
                    line = line.strip()
                    if not line:
                        continue
                    if line.startswith("event:"):
                        event_type = line.split(":", 1)[1].strip()
                    elif line.startswith("data:"):
                        data_str = line.split(":", 1)[1].strip()
                        if data_str == "null":
                            continue

                        if event_type == "error":
                            yield {"event": "error", "message": data_str}
                            return

                        if event_type == "heartbeat":
                            yield {"event": "heartbeat"}
                            continue

                        if event_type == "generating":
                            if not entered_generating:
                                entered_generating = True
                                yield {"event": "step", "step": "queue", "state": "done"}
                                yield {"event": "step", "step": "generate", "state": "active"}

                            try:
                                data = json.loads(data_str)
                                err = _check_for_error(data)
                                if err:
                                    yield {"event": "error", "message": err}
                                    return
                                msg = _extract_progress_message(data)
                                if msg:
                                    yield {"event": "progress", "message": msg}
                            except json.JSONDecodeError:
                                pass

                        if event_type == "complete":
                            try:
                                data = json.loads(data_str)
                            except json.JSONDecodeError:
                                yield {"event": "error", "message": "Failed to parse result"}
                                return

                            err = _check_for_error(data)
                            if err:
                                yield {"event": "error", "message": err}
                                return

                            flac_path = _extract_flac_path(data)
                            if not flac_path:
                                yield {"event": "error", "message": "No FLAC in result"}
                                return
                            break

        except Exception as e:
            yield {"event": "error", "message": f"Generation failed: {e}"}
            return

        if not flac_path:
            yield {"event": "error", "message": "Stream ended without completion"}
            return

        # Mark generation phases done
        if not entered_generating:
            yield {"event": "step", "step": "queue", "state": "done"}
        yield {"event": "step", "step": "generate", "state": "done"}
        yield {"event": "step", "step": "decode", "state": "done"}
        yield {"event": "step", "step": "save", "state": "active"}

        # Step 6: Download FLAC
        try:
            filename = Path(flac_path).name
            local_path = AUDIO_DIR / filename
            await _download_file(client, flac_path, local_path)
        except Exception as e:
            yield {"event": "error", "message": f"Download failed: {e}"}
            return

        yield {"event": "step", "step": "save", "state": "done"}
        yield {"event": "complete", "result": {
            "file_path": str(local_path),
            "filename": filename,
            "seed": seed_used,
        }}
