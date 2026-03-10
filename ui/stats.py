"""Generation statistics tracking."""

import copy
import json
import asyncio
from pathlib import Path
from config import OUTPUTS_DIR

STATS_FILE = OUTPUTS_DIR / "stats.json"
_lock = asyncio.Lock()

_DEFAULT_STATS = {
    "total_generations": 0,
    "successful": 0,
    "failed": 0,
    "retries": 0,
    "total_generation_time_sec": 0.0,
    "total_cover_art_time_sec": 0.0,
    "total_validation_time_sec": 0.0,
    "genres": {},  # genre -> count
    "quality_ratings": {},  # rating -> count
    "crashes_recovered": 0,
}


def _read() -> dict:
    if not STATS_FILE.exists():
        return copy.deepcopy(_DEFAULT_STATS)
    try:
        return json.loads(STATS_FILE.read_text())
    except (json.JSONDecodeError, OSError):
        return copy.deepcopy(_DEFAULT_STATS)


def _write(stats: dict) -> None:
    STATS_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATS_FILE.write_text(json.dumps(stats, indent=2))


async def record_generation(
    genre: str,
    success: bool,
    generation_time: float = 0.0,
    retried: bool = False,
    crash_recovered: bool = False,
) -> None:
    async with _lock:
        s = _read()
        s["total_generations"] += 1
        if success:
            s["successful"] += 1
        else:
            s["failed"] += 1
        if retried:
            s["retries"] += 1
        if crash_recovered:
            s["crashes_recovered"] += 1
        s["total_generation_time_sec"] += generation_time
        s["genres"][genre] = s["genres"].get(genre, 0) + 1
        _write(s)


async def record_quality(rating: str) -> None:
    async with _lock:
        s = _read()
        s["quality_ratings"][rating] = s["quality_ratings"].get(rating, 0) + 1
        _write(s)


async def record_cover_art_time(elapsed: float) -> None:
    async with _lock:
        s = _read()
        s["total_cover_art_time_sec"] += elapsed
        _write(s)


async def record_validation_time(elapsed: float) -> None:
    async with _lock:
        s = _read()
        s["total_validation_time_sec"] += elapsed
        _write(s)


async def get_stats() -> dict:
    async with _lock:
        s = _read()
    # Compute averages
    total = s["successful"] or 1
    s["avg_generation_time_sec"] = round(s["total_generation_time_sec"] / total, 1)
    s["avg_cover_art_time_sec"] = round(s["total_cover_art_time_sec"] / total, 1) if s["total_cover_art_time_sec"] else 0
    s["success_rate_pct"] = round(s["successful"] / max(s["total_generations"], 1) * 100, 1)
    return s
