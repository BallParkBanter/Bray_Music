import json
import pytest
import pytest_asyncio
import sys
from pathlib import Path
from unittest.mock import patch, AsyncMock

sys.path.insert(0, str(Path(__file__).parent.parent.parent))


# ─── Root ─────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_root_serves_html(test_client):
    resp = await test_client.get("/")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
    assert "Bray Music Studio" in resp.text


# ─── Generate ─────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_generate_success(test_client, patch_outputs):
    import config

    # Create a fake FLAC file
    fake_flac = config.AUDIO_DIR / "fake-output.flac"
    fake_flac.write_bytes(b"FLAC")

    mock_result = {"file_path": str(fake_flac), "seed": 12345}

    with patch("gradio_client.generate", new=AsyncMock(return_value=mock_result)), \
         patch("cover_art.generate_cover", new=AsyncMock(return_value=None)):
        resp = await test_client.post("/generate", json={
            "title": "My Test Song",
            "description": "A peaceful rock ballad",
        })

    assert resp.status_code == 200
    data = resp.json()
    assert data["track"]["title"] == "My Test Song"
    assert data["track"]["seed"] == 12345
    assert data["status"] == "ok"

    # Verify it was saved to history
    hist = await test_client.get("/history")
    assert hist.json()["total"] == 1


@pytest.mark.asyncio
async def test_generate_missing_description(test_client):
    resp = await test_client.post("/generate", json={"title": "No desc"})
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_generate_duration_out_of_range(test_client):
    resp = await test_client.post("/generate", json={
        "title": "Too long",
        "description": "A song",
        "duration": 10.0,  # max is 8
    })
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_generate_acestep_error(test_client):
    with patch("gradio_client.generate", new=AsyncMock(side_effect=RuntimeError("GPU error"))):
        resp = await test_client.post("/generate", json={
            "title": "Fail",
            "description": "A song that fails",
        })
    assert resp.status_code == 502


# ─── History ──────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_history_empty(test_client):
    resp = await test_client.get("/history")
    assert resp.status_code == 200
    data = resp.json()
    assert data["tracks"] == []
    assert data["total"] == 0


@pytest.mark.asyncio
async def test_history_sorted_newest_first(test_client, patch_outputs):
    import history as h
    from models import TrackMeta

    tracks = [
        TrackMeta(id=f"t{i}", title=f"Song {i}", description="d",
                  duration_sec=60.0, filename=f"t{i}.flac",
                  created_at=f"2026-03-03T1{i}:00:00+00:00")
        for i in range(3)
    ]
    for t in tracks:
        await h.append(t)

    resp = await test_client.get("/history?sort=newest")
    data = resp.json()
    titles = [t["title"] for t in data["tracks"]]
    assert titles == ["Song 2", "Song 1", "Song 0"]


@pytest.mark.asyncio
async def test_history_search(test_client, patch_outputs):
    import history as h
    from models import TrackMeta

    await h.append(TrackMeta(id="a", title="Amazing Grace", description="hymn",
                             duration_sec=60.0, filename="a.flac",
                             created_at="2026-03-03T10:00:00+00:00"))
    await h.append(TrackMeta(id="b", title="Rock Anthem", description="rock",
                             duration_sec=60.0, filename="b.flac",
                             created_at="2026-03-03T11:00:00+00:00"))

    resp = await test_client.get("/history?search=grace")
    data = resp.json()
    assert data["total"] == 1
    assert data["tracks"][0]["title"] == "Amazing Grace"


# ─── Audio / Cover ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_audio_serves_flac(test_client, patch_outputs):
    import config
    flac = config.AUDIO_DIR / "test.flac"
    flac.write_bytes(b"fLaC" + b"\x00" * 100)

    resp = await test_client.get("/audio/test.flac")
    assert resp.status_code == 200
    assert "audio" in resp.headers["content-type"]


@pytest.mark.asyncio
async def test_audio_not_found(test_client):
    resp = await test_client.get("/audio/missing.flac")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_cover_serves_png(test_client, patch_outputs):
    import config
    png = config.COVERS_DIR / "cover.png"
    png.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100)

    resp = await test_client.get("/cover/cover.png")
    assert resp.status_code == 200
    assert "image/png" in resp.headers["content-type"]


# ─── Delete ───────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_delete_track(test_client, patch_outputs, sample_track):
    import history as h
    import config

    # Create fake audio file
    flac = config.AUDIO_DIR / sample_track.filename
    flac.write_bytes(b"FLAC")
    await h.append(sample_track)

    resp = await test_client.delete(f"/track/{sample_track.id}")
    assert resp.status_code == 200
    assert resp.json()["status"] == "deleted"
    assert not flac.exists()

    hist = await test_client.get("/history")
    assert hist.json()["total"] == 0


@pytest.mark.asyncio
async def test_delete_nonexistent(test_client):
    resp = await test_client.delete("/track/does-not-exist")
    assert resp.status_code == 404


# ─── Health ───────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_health_endpoint(test_client):
    resp = await test_client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert "acestep" in data


# ─── Streaming Endpoint ──────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_generate_stream_success(test_client, patch_outputs):
    """Test /generate-stream returns SSE events and creates a track."""
    import config

    # Create a fake FLAC file
    fake_flac = config.AUDIO_DIR / "stream-output.flac"
    fake_flac.write_bytes(b"FLAC")

    async def fake_streaming(req):
        yield {"event": "step", "step": "submit", "state": "done"}
        yield {"event": "step", "step": "queue", "state": "active"}
        yield {"event": "step", "step": "queue", "state": "done"}
        yield {"event": "step", "step": "generate", "state": "active"}
        yield {"event": "progress", "message": "LM planning..."}
        yield {"event": "step", "step": "generate", "state": "done"}
        yield {"event": "step", "step": "decode", "state": "done"}
        yield {"event": "step", "step": "save", "state": "active"}
        yield {"event": "step", "step": "save", "state": "done"}
        yield {"event": "complete", "result": {
            "file_path": str(fake_flac),
            "filename": "stream-output.flac",
            "seed": 99999,
        }}

    with patch("gradio_client.generate_streaming", new=fake_streaming), \
         patch("cover_art.generate_cover", new=AsyncMock(return_value=None)):
        resp = await test_client.post("/generate-stream", json={
            "title": "Stream Test",
            "description": "Test streaming generation",
        })

    assert resp.status_code == 200
    assert "text/event-stream" in resp.headers.get("content-type", "")

    # Parse SSE events
    events = []
    for line in resp.text.strip().split("\n"):
        line = line.strip()
        if line.startswith("data: "):
            events.append(json.loads(line[6:]))

    # Should have step events, a track event, and a done event
    step_events = [e for e in events if e.get("event") == "step"]
    track_events = [e for e in events if e.get("event") == "track"]
    done_events = [e for e in events if e.get("event") == "done"]
    progress_events = [e for e in events if e.get("event") == "progress"]

    assert len(step_events) > 0, "Should have step events"
    assert len(track_events) == 1, "Should have exactly one track event"
    assert len(done_events) == 1, "Should have a done event"
    assert len(progress_events) >= 1, "Should have progress events"

    # Track should have expected fields
    track = track_events[0]["track"]
    assert track["title"] == "Stream Test"
    assert track["seed"] == 99999
    assert track["filename"] == "stream-output.flac"

    # Verify it was saved to history
    hist = await test_client.get("/history")
    assert hist.json()["total"] >= 1


@pytest.mark.asyncio
async def test_generate_stream_error(test_client, patch_outputs):
    """Test /generate-stream handles errors from ACE-Step."""
    async def fake_streaming_error(req):
        yield {"event": "step", "step": "submit", "state": "done"}
        yield {"event": "step", "step": "queue", "state": "active"}
        yield {"event": "error", "message": "GPU out of memory"}

    with patch("gradio_client.generate_streaming", new=fake_streaming_error):
        resp = await test_client.post("/generate-stream", json={
            "title": "Error Test",
            "description": "Should fail gracefully",
        })

    assert resp.status_code == 200  # SSE stream always starts 200
    events = []
    for line in resp.text.strip().split("\n"):
        line = line.strip()
        if line.startswith("data: "):
            events.append(json.loads(line[6:]))

    error_events = [e for e in events if e.get("event") == "error"]
    assert len(error_events) >= 1
    assert "GPU out of memory" in error_events[-1]["message"]

    # Should NOT have saved a track
    hist = await test_client.get("/history")
    assert hist.json()["total"] == 0


@pytest.mark.asyncio
async def test_generate_stream_missing_description(test_client):
    """Test /generate-stream validates input."""
    resp = await test_client.post("/generate-stream", json={
        "title": "No Desc",
        "description": "",
    })
    assert resp.status_code == 422
