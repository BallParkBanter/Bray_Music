import re
import asyncio
import json
import logging
import os
import uuid
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
from config import ACESTEP_URL, AUDIO_DIR, COVERS_DIR, OUTPUTS_DIR
from models import GenerateRequest, GenerateResponse, HistoryResponse, TrackMeta, Playlist, PlaylistResponse

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Bray Music Studio")

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


@app.post("/generate", response_model=GenerateResponse)
async def generate(req: GenerateRequest, background_tasks: BackgroundTasks):
    track_id = str(uuid.uuid4())
    genre_hint = _extract_genre(req.description)

    if req.include_vocals and not (req.lyrics and req.lyrics.strip()):
        try:
            generated_lyrics = await lyrics_gen.generate_lyrics(req.description)
            if generated_lyrics:
                req.lyrics = generated_lyrics
                logger.info(f"Generated lyrics ({len(generated_lyrics)} chars) for Simple mode")
        except Exception as e:
            logger.warning(f"Lyrics generation failed, proceeding without: {e}")

    try:
        result = await gradio_client.generate(req)
    except Exception as e:
        logger.error(f"Generation failed: {e}")
        raise HTTPException(status_code=502, detail=f"ACE-Step error: {e}")

    file_path = result["file_path"]
    filename = Path(file_path).name if file_path else f"{track_id}.flac"

    track = TrackMeta(
        id=track_id,
        title=req.title,
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
    )

    await history_mod.append(track)
    background_tasks.add_task(_bg_cover, track)

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
    queue: asyncio.Queue = asyncio.Queue()
    _jobs[job_id] = queue

    # Launch the generation as an independent task
    asyncio.create_task(
        _run_generation(job_id, track_id, genre_hint, req, queue)
    )

    async def event_stream():
        try:
            while True:
                evt = await queue.get()
                if evt is None:
                    # Sentinel: generation task is done
                    break
                yield "data: " + json.dumps(evt) + "\n\n"
                if evt.get("event") in ("done", "error"):
                    break
        finally:
            # Clean up job reference (generation task handles its own completion)
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

    try:
        # Step: lyrics generation
        if req.include_vocals and not (req.lyrics and req.lyrics.strip()):
            await emit({"event": "step", "step": "lyrics", "state": "active"})
            try:
                generated_lyrics = await lyrics_gen.generate_lyrics(req.description)
                if generated_lyrics:
                    req.lyrics = generated_lyrics
                    logger.info(f"Generated lyrics ({len(generated_lyrics)} chars) for Simple mode")
                    await emit({"event": "lyrics", "text": generated_lyrics})
                else:
                    logger.warning("Lyrics generation returned empty, proceeding without")
            except Exception as e:
                logger.warning(f"Lyrics generation failed: {e}")
            await emit({"event": "step", "step": "lyrics", "state": "done"})

        await emit({"event": "step", "step": "submit", "state": "active"})

        # Step: ACE-Step generation (streaming)
        result_data = None
        try:
            async for evt in gradio_client.generate_streaming(req):
                await emit(evt)

                if evt.get("event") == "complete":
                    result_data = evt["result"]
                elif evt.get("event") == "error":
                    await emit(None)  # sentinel
                    return
        except Exception as e:
            logger.error("Stream generation error: %s", e)
            await emit({"event": "error", "message": str(e)})
            await emit(None)
            return

        if not result_data:
            await emit({"event": "error", "message": "No result from generator"})
            await emit(None)
            return

        # Step: save track to history (this ALWAYS runs, even if client disconnected)
        file_path = result_data["file_path"]
        filename = result_data["filename"]

        track = TrackMeta(
            id=track_id,
            title=req.title,
            description=req.description,
            genre_hint=genre_hint,
            duration_sec=_get_audio_duration(file_path) or (req.duration * 60),
            filename=filename,
            cover_art=None,
            cover_gradient=_gradient_for(track_id),
            emoji=_emoji_for(genre_hint),
            created_at=datetime.now(timezone.utc).isoformat(),
            seed=result_data["seed"],
            lyrics=req.lyrics,
        )

        await history_mod.append(track)
        logger.info(f"Track saved: {track.title} ({filename})")

        await emit({"event": "track", "track": track.model_dump()})
        await emit({"event": "step", "step": "cover", "state": "active"})

        # Start cover art (also independent)
        asyncio.create_task(_bg_cover(track))

        await emit({"event": "done"})

    except Exception as e:
        logger.error("Generation task fatal error: %s", e)
        await emit({"event": "error", "message": str(e)})
    finally:
        await emit(None)  # sentinel to close SSE stream
        _jobs.pop(job_id, None)


async def _bg_cover(track: TrackMeta) -> None:
    try:
        cover_file = await cover_art_mod.generate_cover(track)
        if cover_file:
            await history_mod.update_cover(track.id, cover_file)
            logger.info(f"Cover art saved: {cover_file}")
    except Exception as e:
        logger.error(f"Background cover art failed for {track.id}: {e}")


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
    genres = [
        "rock", "pop", "jazz", "classical", "hip hop", "electronic", "folk",
        "country", "r&b", "metal", "indie", "ambient", "blues", "reggae",
        "soul", "punk", "latin", "dance", "orchestral",
    ]
    desc_lower = description.lower()
    for g in genres:
        if g in desc_lower:
            return g
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
        "country": "\U0001f920", "r&b": "\U0001f399\ufe0f",
        "metal": "\U0001f918", "indie": "\U0001f3b6",
        "ambient": "\U0001f30a", "blues": "\U0001f3b5",
        "reggae": "\U0001f334", "soul": "\u2764\ufe0f",
        "punk": "\u26a1", "latin": "\U0001f483", "dance": "\U0001f57a",
        "orchestral": "\U0001f3bc",
    }
    return mapping.get(genre, "\U0001f3b5")
