import re
import asyncio
import json
import logging
import os
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

import httpx
from fastapi import BackgroundTasks, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

import cover_art as cover_art_mod
import gradio_client
import lyrics_gen
import history as history_mod
import validation as validation_mod
from config import ACESTEP_URL, AUDIO_DIR, COVERS_DIR, OUTPUTS_DIR
from models import GenerateRequest, GenerateResponse, HistoryResponse, TrackMeta, Playlist, PlaylistResponse

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Pre-warm Ollama model on startup to avoid first-song timeout."""
    logger.info("Startup: Pre-warming Ollama gemma3:12b...")
    try:
        was_cold = await lyrics_gen.ensure_model_loaded()
        if was_cold:
            logger.info("Startup: Ollama model loaded into GPU (cold start)")
        else:
            logger.info("Startup: Ollama model already warm")
    except Exception as e:
        logger.warning(f"Startup: Ollama pre-warm failed (will retry on first generation): {e}")
    yield


app = FastAPI(title="Bray Music Studio", lifespan=lifespan)

STATIC_DIR = Path(__file__).parent / "static"

# In-flight generation jobs: job_id -> asyncio.Queue of SSE events
# The generation runs as an independent task; SSE stream reads from the queue.
# If client disconnects, generation still finishes and saves.
_jobs: dict[str, asyncio.Queue] = {}


# ─── Routes ───────────────────────────────────────────────────────────────────


@app.get("/", response_class=HTMLResponse)
async def root():
    html = (STATIC_DIR / "index.html").read_text()
    return HTMLResponse(content=html)


@app.get("/library", response_class=HTMLResponse)
async def library_page():
    html = (STATIC_DIR / "library.html").read_text()
    return HTMLResponse(content=html)


@app.get("/song/{track_id}", response_class=HTMLResponse)
async def song_page(track_id: str):
    track = await history_mod.get(track_id)
    if not track:
        raise HTTPException(status_code=404, detail="Track not found")
    html = (STATIC_DIR / "song.html").read_text()
    return HTMLResponse(content=html)


def _get_audio_duration(file_path: str) -> float:
    """Read actual duration from FLAC file header."""
    try:
        with open(file_path, "rb") as f:
            magic = f.read(4)
            if magic != b"fLaC":
                return 0.0
            header = f.read(4)
            block_type = header[0] & 0x7F
            block_size = int.from_bytes(header[1:4], "big")
            if block_type != 0 or block_size < 18:
                return 0.0
            data = f.read(block_size)
            sr_bits = (data[10] << 12) | (data[11] << 4) | (data[12] >> 4)
            total = ((data[13] & 0x0F) << 32) | (data[14] << 24) | (data[15] << 16) | (data[16] << 8) | data[17]
            if sr_bits > 0:
                return round(total / sr_bits, 1)
    except Exception as e:
        logger.warning("Could not read audio duration: " + str(e))
    return 0.0


def _initial_title(req: GenerateRequest) -> tuple[str, bool]:
    """Return (title, needs_ai_title). Uses description excerpt if title is empty."""
    if req.title and req.title.strip():
        return req.title.strip(), False
    desc = req.description.strip()
    truncated = desc[:60] + ("…" if len(desc) > 60 else "")
    return truncated, True


@app.post("/generate", response_model=GenerateResponse)
async def generate(req: GenerateRequest, background_tasks: BackgroundTasks):
    track_id = str(uuid.uuid4())
    genre_hint = _extract_genre(req.description)
    title, needs_ai_title = _initial_title(req)

    if req.include_vocals and not (req.lyrics and req.lyrics.strip()):
        try:
            generated_lyrics = await lyrics_gen.generate_lyrics(req.description, genre=genre_hint)
            if generated_lyrics:
                req.lyrics = generated_lyrics
                logger.info(f"Generated lyrics ({len(generated_lyrics)} chars) for Simple mode")
        except Exception as e:
            logger.warning(f"Lyrics generation failed, proceeding without: {e}")

    try:
        result = await gradio_client.generate(req, genre_hint=genre_hint)
    except Exception as e:
        logger.error(f"Generation failed: {e}")
        raise HTTPException(status_code=502, detail=f"ACE-Step error: {e}")

    file_path = result["file_path"]
    filename = Path(file_path).name if file_path else f"{track_id}.flac"

    track = TrackMeta(
        id=track_id,
        title=title,
        description=req.description,
        genre_hint=genre_hint,
        duration_sec=_get_audio_duration(file_path) or (req.duration * 60),
        filename=filename,
        cover_art=None,
        cover_gradient=_gradient_for(track_id),
        emoji=_emoji_for(genre_hint),
        created_at=datetime.now(timezone.utc).isoformat(),
        seed=result["seed"],
        lyrics=req.lyrics,
        bpm=req.bpm,
        key=req.key,
        creativity=req.creativity,
        include_vocals=req.include_vocals,
        enhance_lyrics=req.enhance_lyrics,
    )

    await history_mod.append(track)
    background_tasks.add_task(_bg_validate_and_cover, track, None, needs_ai_title)

    return GenerateResponse(track=track)


@app.post("/generate-stream")
async def generate_stream(req: GenerateRequest):
    """SSE streaming endpoint with disconnect-safe generation.

    The generation runs as an independent asyncio task that writes events
    to a queue. The SSE stream reads from the queue. If the client
    disconnects, the generation task keeps running and still saves the
    track to history when done.
    """
    job_id = str(uuid.uuid4())
    track_id = str(uuid.uuid4())
    genre_hint = _extract_genre(req.description)
    title, needs_ai_title = _initial_title(req)
    queue: asyncio.Queue = asyncio.Queue()
    _jobs[job_id] = queue

    # Launch the generation as an independent task
    asyncio.create_task(
        _run_generation(job_id, track_id, genre_hint, req, queue, title, needs_ai_title)
    )

    async def event_stream():
        try:
            while True:
                try:
                    evt = await asyncio.wait_for(queue.get(), timeout=15)
                except asyncio.TimeoutError:
                    # Send heartbeat to keep SSE connection alive through proxies
                    yield ": heartbeat\n\n"
                    continue
                if evt is None:
                    break
                yield "data: " + json.dumps(evt) + "\n\n"
                if evt.get("event") in ("done", "error"):
                    break
        finally:
            _jobs.pop(job_id, None)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


async def _run_generation(
    job_id: str,
    track_id: str,
    genre_hint: str,
    req: GenerateRequest,
    queue: asyncio.Queue,
    title: str = "",
    needs_ai_title: bool = False,
):
    """Independent generation task. Puts events on the queue for the SSE stream.

    Crucially, this runs to completion even if the SSE client disconnects,
    ensuring the track is always saved to history.
    """
    async def emit(evt: dict):
        try:
            await queue.put(evt)
        except Exception:
            pass  # Queue might be gone if client disconnected; that is fine

    job_start = time.time()
    logger.info("=" * 60)
    logger.info(f"[GEN {track_id[:8]}] NEW GENERATION STARTED")
    logger.info(f"[GEN {track_id[:8]}] Description: {req.description}")
    logger.info(f"[GEN {track_id[:8]}] Title: '{title}' (needs_ai_title={needs_ai_title})")
    logger.info(f"[GEN {track_id[:8]}] Genre: {genre_hint} | Vocals: {req.include_vocals} | BPM: {req.bpm or 'auto'} | Key: {req.key or 'auto'} | Creativity: {req.creativity}")
    logger.info(f"[GEN {track_id[:8]}] Duration: {req.duration or 'auto (LM determines from lyrics)'} | Enhance: {req.enhance_lyrics} | Seed: {req.seed or 'random'}")
    logger.info(f"[GEN {track_id[:8]}] Lyrics provided: {bool(req.lyrics and req.lyrics.strip())} ({len(req.lyrics)} chars)")

    try:
        # Step: ensure Ollama model is loaded (may take 20-25s on cold start)
        if req.include_vocals and not (req.lyrics and req.lyrics.strip()):
            await emit({"event": "step", "step": "model_load", "state": "active"})
            step_start = time.time()
            logger.info(f"[GEN {track_id[:8]}] MODEL: Checking if Ollama model is loaded...")
            try:
                was_cold = await lyrics_gen.ensure_model_loaded()
                elapsed = time.time() - step_start
                if was_cold:
                    logger.info(f"[GEN {track_id[:8]}] MODEL: Cold-loaded in {elapsed:.1f}s")
                    model_detail = f"\U0001f9e0 Ollama gemma3:12b loaded on Optimus in {elapsed:.1f}s"
                else:
                    logger.info(f"[GEN {track_id[:8]}] MODEL: Already warm ({elapsed:.1f}s)")
                    model_detail = "\U0001f9e0 Ollama gemma3:12b ready on Optimus"
            except Exception as e:
                elapsed = time.time() - step_start
                logger.warning(f"[GEN {track_id[:8]}] MODEL: Pre-load failed after {elapsed:.1f}s: {e}")
                model_detail = f"\u26a0\ufe0f Model pre-load failed ({elapsed:.1f}s)"
            await emit({"event": "step", "step": "model_load", "state": "done", "detail": model_detail})

            await emit({"event": "step", "step": "lyrics", "state": "active"})
            step_start = time.time()
            logger.info(f"[GEN {track_id[:8]}] LYRICS: Starting generation via Ollama...")
            lyrics_detail = None
            try:
                generated_lyrics = await lyrics_gen.generate_lyrics(req.description, genre=genre_hint)
                elapsed = time.time() - step_start
                if generated_lyrics:
                    req.lyrics = generated_lyrics
                    logger.info(f"[GEN {track_id[:8]}] LYRICS: Generated {len(generated_lyrics)} chars in {elapsed:.1f}s")
                    await emit({"event": "lyrics", "text": generated_lyrics})
                    lyrics_detail = f"\u270d\ufe0f Wrote {len(generated_lyrics)} chars of lyrics in {elapsed:.1f}s"
                else:
                    logger.warning(f"[GEN {track_id[:8]}] LYRICS: Returned empty after {elapsed:.1f}s, proceeding without")
                    lyrics_detail = f"\u26a0\ufe0f No lyrics generated ({elapsed:.1f}s)"
            except Exception as e:
                elapsed = time.time() - step_start
                logger.warning(f"[GEN {track_id[:8]}] LYRICS: Failed after {elapsed:.1f}s: {e}")
                lyrics_detail = f"\u26a0\ufe0f Lyrics failed ({elapsed:.1f}s)"
            await emit({"event": "step", "step": "lyrics", "state": "done", "detail": lyrics_detail})

        # Generate title while Ollama model is still loaded (avoids 22s reload later)
        if needs_ai_title:
            await emit({"event": "step", "step": "title_gen", "state": "active"})
            step_start = time.time()
            logger.info(f"[GEN {track_id[:8]}] TITLE: Generating while Ollama is warm...")
            title_detail = None
            try:
                ai_title = await lyrics_gen.generate_title(req.description)
                elapsed = time.time() - step_start
                if ai_title:
                    title = ai_title
                    needs_ai_title = False
                    title_detail = f"\U0001f3b5 Title: \u201c{ai_title}\u201d in {elapsed:.1f}s"
                    logger.info(f"[GEN {track_id[:8]}] TITLE: '{ai_title}' in {elapsed:.1f}s")
                else:
                    logger.warning(f"[GEN {track_id[:8]}] TITLE: Returned empty after {elapsed:.1f}s")
                    title_detail = f"\u26a0\ufe0f No title generated ({elapsed:.1f}s)"
            except Exception as e:
                elapsed = time.time() - step_start
                logger.warning(f"[GEN {track_id[:8]}] TITLE: Failed after {elapsed:.1f}s: {e}")
                title_detail = f"\u26a0\ufe0f Title generation failed ({elapsed:.1f}s)"
            await emit({"event": "step", "step": "title_gen", "state": "done", "detail": title_detail})

        await emit({"event": "step", "step": "submit", "state": "active"})

        # Health check: verify ACE-Step is reachable before submitting
        logger.info(f"[GEN {track_id[:8]}] ACESTEP: Checking health...")
        for hc_attempt in range(6):
            if await gradio_client.check_health():
                break
            wait_time = 30
            logger.warning(f"[GEN {track_id[:8]}] ACESTEP: Not reachable, waiting {wait_time}s (attempt {hc_attempt+1}/6)...")
            await emit({"event": "step", "step": "submit", "state": "active",
                        "detail": f"\u23f3 Waiting for ACE-Step ({hc_attempt+1}/6)..."})
            await asyncio.sleep(wait_time)
        else:
            logger.error(f"[GEN {track_id[:8]}] ACESTEP: Unreachable after 3 minutes of waiting")
            await emit({"event": "error", "message": "ACE-Step is not responding. Please try again in a few minutes."})
            await emit(None)
            return

        # Step: ACE-Step generation with retry on crash
        max_retries = 1
        result_data = None
        for attempt in range(max_retries + 1):
            step_start = time.time()
            logger.info(f"[GEN {track_id[:8]}] ACESTEP: Submitting to ACE-Step{' (retry)' if attempt > 0 else ''}...")
            ace_error = None
            try:
                async for evt in gradio_client.generate_streaming(req, genre_hint=genre_hint):
                    await emit(evt)

                    if evt.get("event") == "complete":
                        result_data = evt["result"]
                        elapsed = time.time() - step_start
                        logger.info(f"[GEN {track_id[:8]}] ACESTEP: Complete in {elapsed:.1f}s — file: {result_data.get('filename', '?')}, seed: {result_data.get('seed', '?')}")
                    elif evt.get("event") == "error":
                        elapsed = time.time() - step_start
                        ace_error = evt.get("message", "Unknown error")
                        logger.error(f"[GEN {track_id[:8]}] ACESTEP: Error after {elapsed:.1f}s: {ace_error}")
                        break
                    elif evt.get("event") == "progress":
                        logger.info(f"[GEN {track_id[:8]}] ACESTEP: Progress {evt.get('progress', '?')}%")
            except Exception as e:
                elapsed = time.time() - step_start
                ace_error = str(e)
                logger.error(f"[GEN {track_id[:8]}] ACESTEP: Stream error after {elapsed:.1f}s: {e}")

            if result_data:
                break  # Success

            # Failed — should we retry?
            if attempt < max_retries:
                logger.info(f"[GEN {track_id[:8]}] ACESTEP: Will retry (attempt {attempt+2}/{max_retries+1})...")
                await emit({"event": "step", "step": "submit", "state": "active",
                            "detail": "\u26a0\ufe0f ACE-Step crashed — waiting for restart, will retry..."})
                # Wait for ACE-Step to restart (systemd takes 60-90s)
                for wait_attempt in range(6):
                    await asyncio.sleep(30)
                    if await gradio_client.check_health():
                        logger.info(f"[GEN {track_id[:8]}] ACESTEP: Back online after {(wait_attempt+1)*30}s")
                        break
                else:
                    logger.error(f"[GEN {track_id[:8]}] ACESTEP: Not recovered after 3 min wait")
                    await emit({"event": "error", "message": "ACE-Step crashed and did not recover"})
                    await emit(None)
                    return
            else:
                await emit({"event": "error", "message": f"Generation failed: {ace_error}"})
                await emit(None)
                return

        if not result_data:
            logger.error(f"[GEN {track_id[:8]}] ACESTEP: No result after all attempts")
            await emit({"event": "error", "message": "No result from generator"})
            await emit(None)
            return

        # Step: save track to history (this ALWAYS runs, even if client disconnected)
        file_path = result_data["file_path"]
        filename = result_data["filename"]
        duration = _get_audio_duration(file_path) or (req.duration * 60)

        track = TrackMeta(
            id=track_id,
            title=title,
            description=req.description,
            genre_hint=genre_hint,
            duration_sec=duration,
            filename=filename,
            cover_art=None,
            cover_gradient=_gradient_for(track_id),
            emoji=_emoji_for(genre_hint),
            created_at=datetime.now(timezone.utc).isoformat(),
            seed=result_data["seed"],
            lyrics=req.lyrics,
            bpm=req.bpm,
            key=req.key,
            creativity=req.creativity,
            include_vocals=req.include_vocals,
            enhance_lyrics=req.enhance_lyrics,
        )

        await history_mod.append(track)
        logger.info(f"[GEN {track_id[:8]}] SAVED: '{track.title}' | {filename} | {duration:.1f}s | seed={result_data['seed']}")

        dur_m = int(duration // 60)
        dur_s = int(duration % 60)
        save_detail = f"\U0001f4be Saved \u2014 {dur_m}:{dur_s:02d} \u00b7 FLAC \u00b7 seed {result_data['seed']}"
        await emit({"event": "step", "step": "save", "state": "done", "detail": save_detail})
        await emit({"event": "track", "track": track.model_dump()})

        # Validate + cover art (runs inline so SSE stream stays open)
        await _bg_validate_and_cover(track, queue=queue, needs_ai_title=needs_ai_title)

    except Exception as e:
        elapsed = time.time() - job_start
        logger.error(f"[GEN {track_id[:8]}] FATAL ERROR after {elapsed:.1f}s: {e}")
        await emit({"event": "error", "message": str(e)})
        await emit(None)
    finally:
        total = time.time() - job_start
        logger.info(f"[GEN {track_id[:8]}] TOTAL TIME: {total:.1f}s")
        logger.info("=" * 60)
        _jobs.pop(job_id, None)


async def _bg_validate_and_cover(
    track: TrackMeta,
    queue: asyncio.Queue | None = None,
    needs_ai_title: bool = False,
) -> None:
    """Validate vocal quality (if applicable), then generate cover art conditionally."""
    async def emit(evt: dict):
        if queue:
            try:
                await queue.put(evt)
            except Exception:
                pass

    tid = track.id[:8]

    # AI title generation (if no user-provided title)
    if needs_ai_title:
        step_start = time.time()
        logger.info(f"[POST {tid}] TITLE: Generating AI title via Ollama...")
        try:
            ai_title = await lyrics_gen.generate_title(track.description)
            elapsed = time.time() - step_start
            if ai_title:
                await history_mod.update_title(track.id, ai_title)
                track.title = ai_title
                await emit({"event": "title", "title": ai_title})
                logger.info(f"[POST {tid}] TITLE: '{ai_title}' in {elapsed:.1f}s")
            else:
                logger.warning(f"[POST {tid}] TITLE: Returned empty after {elapsed:.1f}s")
        except Exception as e:
            elapsed = time.time() - step_start
            logger.warning(f"[POST {tid}] TITLE: Failed after {elapsed:.1f}s: {e}")

    is_instrumental = (
        not track.lyrics
        or not track.lyrics.strip()
        or track.lyrics.strip() == "[Instrumental]"
    )
    logger.info(f"[POST {tid}] Type: {'instrumental' if is_instrumental else 'vocal'}")

    # Step 1: Whisper validation (vocal tracks only)
    quality_rating = None
    if not is_instrumental:
        await emit({"event": "step", "step": "validate", "state": "active"})
        step_start = time.time()
        logger.info(f"[POST {tid}] WHISPER: Starting validation for {track.filename}...")
        validate_detail = None
        try:
            result = await validation_mod.validate_track(track.filename)
            elapsed = time.time() - step_start
            if result:
                quality_rating = result["quality_rating"]
                score_pct = round((result["quality_score"] or 0) * 100)
                await history_mod.update_quality(
                    track.id, result["quality_score"], quality_rating,
                )
                await emit({
                    "event": "quality",
                    "rating": quality_rating,
                    "score": result["quality_score"],
                })
                rating_emoji = {
                    "GREAT": "\U0001f31f", "GOOD": "\u2705",
                    "FAIR": "\U0001f7e1", "POOR": "\U0001f534",
                }.get(quality_rating, "\U0001f3a4")
                validate_detail = f"{rating_emoji} Vocals verified: {quality_rating} ({score_pct}%) in {elapsed:.1f}s"
                logger.info(f"[POST {tid}] WHISPER: {quality_rating} (score={result['quality_score']:.1f}) in {elapsed:.1f}s")
            else:
                logger.warning(f"[POST {tid}] WHISPER: No result after {elapsed:.1f}s")
                validate_detail = f"\u26a0\ufe0f Validation unavailable ({elapsed:.1f}s)"
        except Exception as e:
            elapsed = time.time() - step_start
            logger.warning(f"[POST {tid}] WHISPER: Failed after {elapsed:.1f}s: {e}")
            validate_detail = f"\u26a0\ufe0f Validation failed ({elapsed:.1f}s)"
        await emit({"event": "step", "step": "validate", "state": "done", "detail": validate_detail})

    # Step 2: Conditional cover art
    # Generate cover art unless whisper explicitly rated it FAIR or POOR
    should_generate_cover = is_instrumental or quality_rating in ("GOOD", "GREAT") or quality_rating is None
    logger.info(f"[POST {tid}] COVER: should_generate={should_generate_cover} (instrumental={is_instrumental}, quality={quality_rating})")

    await emit({"event": "step", "step": "cover", "state": "active"})
    cover_detail = None
    if should_generate_cover:
        step_start = time.time()
        logger.info(f"[POST {tid}] COVER: Generating AI cover art...")
        try:
            cover_file = await cover_art_mod.generate_cover(track)
            elapsed = time.time() - step_start
            if cover_file:
                await history_mod.update_cover(track.id, cover_file)
                await emit({"event": "cover_art", "cover_art": cover_file})
                cover_detail = f"\U0001f3a8 Cover art created in {elapsed:.1f}s"
                logger.info(f"[POST {tid}] COVER: Saved {cover_file} in {elapsed:.1f}s")
            else:
                logger.warning(f"[POST {tid}] COVER: Returned empty after {elapsed:.1f}s")
                cover_detail = f"\u26a0\ufe0f Cover art empty ({elapsed:.1f}s)"
        except Exception as e:
            elapsed = time.time() - step_start
            logger.error(f"[POST {tid}] COVER: Failed after {elapsed:.1f}s: {e}")
            cover_detail = f"\u26a0\ufe0f Cover art failed ({elapsed:.1f}s)"
    else:
        logger.info(f"[POST {tid}] COVER: Skipped — using gradient fallback")
        cover_detail = "\U0001f3a8 Using gradient cover (quality too low for AI art)"
    await emit({"event": "step", "step": "cover", "state": "done", "detail": cover_detail})

    logger.info(f"[POST {tid}] Post-processing complete")
    await emit({"event": "done"})
    await emit(None)  # sentinel


@app.get("/history", response_model=HistoryResponse)
async def get_history(sort: str = "newest", search: str = "", filter: str = "all"):
    tracks = await history_mod.load()

    if search:
        q = search.lower()
        tracks = [t for t in tracks if q in t.title.lower() or q in t.description.lower()]

    if filter == "favorites":
        tracks = [t for t in tracks if t.favorite]
    elif filter == "instrumental":
        tracks = [t for t in tracks if not t.lyrics or t.lyrics.strip() == "" or t.lyrics.strip() == "[Instrumental]"]
    elif filter == "vocals":
        tracks = [t for t in tracks if t.lyrics and t.lyrics.strip() and t.lyrics.strip() != "[Instrumental]"]

    if sort == "newest":
        tracks = sorted(tracks, key=lambda t: t.created_at, reverse=True)
    elif sort == "oldest":
        tracks = sorted(tracks, key=lambda t: t.created_at)

    return HistoryResponse(tracks=tracks, total=len(tracks))


# ─── Favorite endpoint ───────────────────────────────────────────────────────


@app.post("/track/{track_id}/favorite")
async def toggle_favorite(track_id: str):
    track = await history_mod.get(track_id)
    if not track:
        raise HTTPException(status_code=404, detail="Track not found")
    new_state = await history_mod.toggle_favorite(track_id)
    return {"id": track_id, "favorite": new_state}


# ─── Playlist endpoints ──────────────────────────────────────────────────────


@app.get("/playlists", response_model=PlaylistResponse)
async def list_playlists():
    playlists = await history_mod.load_playlists()
    return PlaylistResponse(playlists=playlists, total=len(playlists))


@app.post("/playlists")
async def create_playlist(req: dict):
    playlist = Playlist(
        id=str(uuid.uuid4()),
        name=req.get("name", "Untitled Playlist"),
        track_ids=[],
        created_at=datetime.now(timezone.utc).isoformat(),
        cover_gradient=_gradient_for(str(uuid.uuid4())),
    )
    await history_mod.save_playlist(playlist)
    return playlist


@app.delete("/playlists/{playlist_id}")
async def delete_playlist(playlist_id: str):
    removed = await history_mod.delete_playlist(playlist_id)
    if not removed:
        raise HTTPException(status_code=404, detail="Playlist not found")
    return {"status": "deleted", "id": playlist_id}


@app.post("/playlists/{playlist_id}/tracks")
async def add_to_playlist(playlist_id: str, req: dict):
    track_id = req.get("track_id")
    if not track_id:
        raise HTTPException(status_code=400, detail="track_id required")
    added = await history_mod.add_track_to_playlist(playlist_id, track_id)
    if not added:
        raise HTTPException(status_code=404, detail="Playlist not found")
    return {"status": "added"}


@app.delete("/playlists/{playlist_id}/tracks/{track_id}")
async def remove_from_playlist(playlist_id: str, track_id: str):
    removed = await history_mod.remove_track_from_playlist(playlist_id, track_id)
    if not removed:
        raise HTTPException(status_code=404, detail="Not found")
    return {"status": "removed"}


@app.get("/audio/{filename}")
async def serve_audio(filename: str, request: Request):
    path = AUDIO_DIR / filename
    if not path.exists():
        raise HTTPException(status_code=404, detail="Audio file not found")

    file_size = path.stat().st_size
    range_header = request.headers.get("range")

    if range_header:
        m = re.match(r"bytes=(\d+)-(\d*)", range_header)
        if m:
            start = int(m.group(1))
            end = int(m.group(2)) if m.group(2) else file_size - 1
            end = min(end, file_size - 1)
            length = end - start + 1

            def iterfile():
                with open(path, "rb") as f:
                    f.seek(start)
                    remaining = length
                    while remaining > 0:
                        chunk = f.read(min(8192, remaining))
                        if not chunk:
                            break
                        remaining -= len(chunk)
                        yield chunk

            return StreamingResponse(
                iterfile(),
                status_code=206,
                media_type="audio/flac",
                headers={
                    "Content-Range": f"bytes {start}-{end}/{file_size}",
                    "Accept-Ranges": "bytes",
                    "Content-Length": str(length),
                },
            )

    return FileResponse(
        path,
        media_type="audio/flac",
        headers={"Accept-Ranges": "bytes"},
    )


@app.get("/cover/{filename}")
async def serve_cover(filename: str):
    path = COVERS_DIR / filename
    if not path.exists():
        raise HTTPException(status_code=404, detail="Cover not found")
    return FileResponse(path, media_type="image/png")


@app.delete("/track/{track_id}")
async def delete_track(track_id: str):
    track = await history_mod.get(track_id)
    if not track:
        raise HTTPException(status_code=404, detail="Track not found")

    removed = await history_mod.remove(track_id)
    if not removed:
        raise HTTPException(status_code=404, detail="Track not found")

    audio_path = AUDIO_DIR / track.filename
    if audio_path.exists():
        audio_path.unlink()

    if track.cover_art:
        cover_path = COVERS_DIR / track.cover_art
        if cover_path.exists():
            cover_path.unlink()

    return {"status": "deleted", "id": track_id}


@app.get("/track/{track_id}", response_model=TrackMeta)
async def get_track(track_id: str):
    track = await history_mod.get(track_id)
    if not track:
        raise HTTPException(status_code=404, detail="Track not found")
    return track


@app.post("/track/{track_id}/regenerate-cover")
async def regenerate_cover(track_id: str):
    track = await history_mod.get(track_id)
    if not track:
        raise HTTPException(status_code=404, detail="Track not found")
    logger.info(f"[REGEN-COVER {track_id[:8]}] Starting cover art regeneration...")
    try:
        cover_file = await cover_art_mod.generate_cover(track)
        if cover_file:
            await history_mod.update_cover(track_id, cover_file)
            logger.info(f"[REGEN-COVER {track_id[:8]}] New cover: {cover_file}")
            return {"cover_art": cover_file}
        raise HTTPException(status_code=500, detail="Cover art generation returned empty")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[REGEN-COVER {track_id[:8]}] Failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/health")
async def health():
    acestep_ok = False
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            r = await client.get(f"{ACESTEP_URL}/gradio_api/info")
            acestep_ok = r.status_code == 200
    except Exception:
        pass

    gpu = "unknown"
    try:
        proc = await asyncio.create_subprocess_exec(
            "nvidia-smi", "--query-gpu=name", "--format=csv,noheader",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await proc.communicate()
        gpu = stdout.decode().strip() or "unavailable"
    except Exception:
        gpu = "nvidia-smi not available"

    return {
        "status": "ok",
        "acestep": "reachable" if acestep_ok else "unreachable",
        "gpu": gpu,
        "outputs_writable": os.access(OUTPUTS_DIR, os.W_OK),
    }


# ─── Helpers ──────────────────────────────────────────────────────────────────


def _extract_genre(description: str) -> str:
    desc_lower = description.lower()
    # Order matters — compound genres FIRST, then specific, then generic.
    # Multi-word matches must come before their single-word components.
    genre_map = [
        # Compound genres (must be checked before their components)
        (["country rock", "southern rock"], "country rock"),
        (["latin pop"], "latin pop"),
        (["k-pop", "kpop", "k pop"], "k-pop"),
        (["j-pop", "jpop", "j pop", "anime"], "j-pop"),
        # Standard genres
        (["rap battle", "rap song", "rapper", "rapping", "hip hop", "hip-hop", "hiphop", "trap"], "hip hop"),
        (["r&b", "r and b", "rnb", "rhythm and blues"], "r&b"),
        (["edm", "techno", "house music", "trance", "dubstep", "electronic"], "electronic"),
        (["heavy metal", "death metal", "thrash", "metalcore"], "metal"),
        (["punk rock", "punk"], "punk"),
        (["indie rock", "indie pop", "indie"], "indie"),
        (["classic rock", "rock anthem", "rock song", "rock"], "rock"),
        (["pop song", "pop music", "pop anthem", "pop"], "pop"),
        (["jazz"], "jazz"),
        (["classical", "orchestra", "symphon", "orchestral"], "classical"),
        (["folk", "acoustic folk"], "folk"),
        (["country", "honky tonk", "bluegrass"], "country"),
        (["metal"], "metal"),
        (["ambient", "chill", "lo-fi", "lofi"], "ambient"),
        (["blues"], "blues"),
        (["reggae", "reggaeton"], "reggae"),
        (["soul", "motown"], "soul"),
        (["latin", "salsa", "bossa nova"], "latin"),
        (["dance", "disco", "club"], "dance"),
        (["gospel", "worship", "hymn", "praise"], "gospel"),
        (["ballad", "love song", "slow song", "acoustic love"], "ballad"),
    ]
    for keywords, genre in genre_map:
        for kw in keywords:
            if kw in desc_lower:
                return genre
    return "music"


def _gradient_for(track_id: str) -> str:
    gradients = [
        "linear-gradient(135deg, #667eea 0%, #764ba2 100%)",
        "linear-gradient(135deg, #f093fb 0%, #f5576c 100%)",
        "linear-gradient(135deg, #4facfe 0%, #00f2fe 100%)",
        "linear-gradient(135deg, #43e97b 0%, #38f9d7 100%)",
        "linear-gradient(135deg, #fa709a 0%, #fee140 100%)",
        "linear-gradient(135deg, #a18cd1 0%, #fbc2eb 100%)",
        "linear-gradient(135deg, #ffecd2 0%, #fcb69f 100%)",
        "linear-gradient(135deg, #ff9a9e 0%, #fecfef 100%)",
    ]
    idx = hash(track_id) % len(gradients)
    return gradients[idx]


def _emoji_for(genre: str) -> str:
    mapping = {
        "rock": "\U0001f3b8", "pop": "\U0001f3a4", "jazz": "\U0001f3b7",
        "classical": "\U0001f3bb", "hip hop": "\U0001f3a7",
        "electronic": "\U0001f39b\ufe0f", "folk": "\U0001fa97",
        "country": "\U0001f920", "country rock": "\U0001f920",
        "r&b": "\U0001f399\ufe0f",
        "metal": "\U0001f918", "indie": "\U0001f3b6",
        "ambient": "\U0001f30a", "blues": "\U0001f3b5",
        "reggae": "\U0001f334", "soul": "\u2764\ufe0f",
        "punk": "\u26a1", "latin": "\U0001f483", "latin pop": "\U0001f483",
        "dance": "\U0001f57a",
        "orchestral": "\U0001f3bc", "gospel": "\U0001f64f",
        "ballad": "\U0001f49c", "j-pop": "\U0001f338",
        "k-pop": "\u2b50",
    }
    return mapping.get(genre, "\U0001f3b5")
