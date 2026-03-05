import asyncio
import json
from pathlib import Path
from models import TrackMeta, Playlist
from config import HISTORY_FILE, PLAYLISTS_FILE

_lock = asyncio.Lock()
_playlist_lock = asyncio.Lock()


async def load() -> list[TrackMeta]:
    if not HISTORY_FILE.exists():
        return []
    async with _lock:
        text = HISTORY_FILE.read_text()
    if not text.strip():
        return []
    raw = json.loads(text)
    return [TrackMeta(**item) for item in raw]


async def append(track: TrackMeta) -> None:
    async with _lock:
        tracks = _read_raw()
        tracks.append(track.model_dump())
        _write_raw(tracks)


async def remove(track_id: str) -> bool:
    async with _lock:
        tracks = _read_raw()
        filtered = [t for t in tracks if t["id"] != track_id]
        if len(filtered) == len(tracks):
            return False
        _write_raw(filtered)
        return True


async def get(track_id: str) -> TrackMeta | None:
    tracks = await load()
    for t in tracks:
        if t.id == track_id:
            return t
    return None


async def update_cover(track_id: str, cover_art: str) -> None:
    async with _lock:
        tracks = _read_raw()
        for t in tracks:
            if t["id"] == track_id:
                t["cover_art"] = cover_art
                break
        _write_raw(tracks)


async def update_quality(track_id: str, score: float, rating: str) -> None:
    async with _lock:
        tracks = _read_raw()
        for t in tracks:
            if t["id"] == track_id:
                t["quality_score"] = score
                t["quality_rating"] = rating
                break
        _write_raw(tracks)


async def toggle_favorite(track_id: str) -> bool:
    """Toggle favorite status, return new state."""
    async with _lock:
        tracks = _read_raw()
        for t in tracks:
            if t["id"] == track_id:
                t["favorite"] = not t.get("favorite", False)
                _write_raw(tracks)
                return t["favorite"]
    return False


def _read_raw() -> list[dict]:
    if not HISTORY_FILE.exists():
        return []
    text = HISTORY_FILE.read_text()
    if not text.strip():
        return []
    return json.loads(text)


def _write_raw(tracks: list[dict]) -> None:
    HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    HISTORY_FILE.write_text(json.dumps(tracks, indent=2))


# ─── Playlist storage ────────────────────────────────────────────────────────


def _read_playlists_raw() -> list[dict]:
    if not PLAYLISTS_FILE.exists():
        return []
    text = PLAYLISTS_FILE.read_text()
    if not text.strip():
        return []
    return json.loads(text)


def _write_playlists_raw(playlists: list[dict]) -> None:
    PLAYLISTS_FILE.parent.mkdir(parents=True, exist_ok=True)
    PLAYLISTS_FILE.write_text(json.dumps(playlists, indent=2))


async def load_playlists() -> list[Playlist]:
    async with _playlist_lock:
        raw = _read_playlists_raw()
    return [Playlist(**item) for item in raw]


async def save_playlist(playlist: Playlist) -> None:
    async with _playlist_lock:
        playlists = _read_playlists_raw()
        playlists.append(playlist.model_dump())
        _write_playlists_raw(playlists)


async def delete_playlist(playlist_id: str) -> bool:
    async with _playlist_lock:
        playlists = _read_playlists_raw()
        filtered = [p for p in playlists if p["id"] != playlist_id]
        if len(filtered) == len(playlists):
            return False
        _write_playlists_raw(filtered)
        return True


async def add_track_to_playlist(playlist_id: str, track_id: str) -> bool:
    async with _playlist_lock:
        playlists = _read_playlists_raw()
        for p in playlists:
            if p["id"] == playlist_id:
                if track_id not in p.get("track_ids", []):
                    p.setdefault("track_ids", []).append(track_id)
                _write_playlists_raw(playlists)
                return True
    return False


async def remove_track_from_playlist(playlist_id: str, track_id: str) -> bool:
    async with _playlist_lock:
        playlists = _read_playlists_raw()
        for p in playlists:
            if p["id"] == playlist_id:
                ids = p.get("track_ids", [])
                if track_id in ids:
                    ids.remove(track_id)
                    _write_playlists_raw(playlists)
                    return True
                return False
    return False
