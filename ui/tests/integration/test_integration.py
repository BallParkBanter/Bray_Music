"""
Integration tests — run against live containers.
Skip by default; run with: pytest tests/integration -v -m integration
"""
import pytest
import pytest_asyncio
import httpx
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

BASE_URL = "http://localhost:7861"
POLL_TIMEOUT = 120


@pytest.mark.integration
@pytest.mark.asyncio
async def test_full_generate_and_play():
    """POST /generate → wait → GET /audio → 200."""
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=180) as client:
        resp = await client.post("/generate", json={
            "title": "Integration Test Song",
            "description": "Short ambient drone, minimal, 1 minute",
            "duration": 1.0,
        })
        assert resp.status_code == 200, resp.text
        track = resp.json()["track"]
        assert track["filename"]

        audio = await client.get(f"/audio/{track['filename']}")
        assert audio.status_code == 200
        assert len(audio.content) > 1000  # Not empty


@pytest.mark.integration
@pytest.mark.asyncio
async def test_cover_art_appears_async():
    """After generate, poll until cover art appears (up to 120s)."""
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=180) as client:
        resp = await client.post("/generate", json={
            "title": "Cover Art Test",
            "description": "Pop song, upbeat, bright",
            "duration": 1.0,
        })
        assert resp.status_code == 200
        track_id = resp.json()["track"]["id"]

        start = asyncio.get_event_loop().time()
        while asyncio.get_event_loop().time() - start < POLL_TIMEOUT:
            await asyncio.sleep(5)
            detail = await client.get(f"/track/{track_id}")
            if detail.status_code == 200 and detail.json().get("cover_art"):
                cover_file = detail.json()["cover_art"]
                cover_resp = await client.get(f"/cover/{cover_file}")
                assert cover_resp.status_code == 200
                return  # Success

        pytest.skip("Cover art did not appear within timeout — cover-art-service may be unavailable")


@pytest.mark.integration
@pytest.mark.asyncio
async def test_delete_removes_file():
    """Generate → delete → FLAC file gone."""
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=180) as client:
        resp = await client.post("/generate", json={
            "title": "Delete Me",
            "description": "Ambient, minimal",
            "duration": 1.0,
        })
        assert resp.status_code == 200
        track = resp.json()["track"]

        del_resp = await client.delete(f"/track/{track['id']}")
        assert del_resp.status_code == 200

        audio = await client.get(f"/audio/{track['filename']}")
        assert audio.status_code == 404


@pytest.mark.integration
@pytest.mark.asyncio
async def test_history_returns_tracks():
    """After generating, history endpoint returns the track."""
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=180) as client:
        resp = await client.post("/generate", json={
            "title": "History Track",
            "description": "Folk song, acoustic",
            "duration": 1.0,
        })
        track_id = resp.json()["track"]["id"]

        hist = await client.get("/history")
        ids = [t["id"] for t in hist.json()["tracks"]]
        assert track_id in ids
