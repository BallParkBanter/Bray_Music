"""Tests for the retry/health-check logic in main._run_generation()."""

import asyncio
import json
import pytest
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch, MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent.parent))


def _make_queue():
    """Create an asyncio.Queue and collect events from it."""
    return asyncio.Queue()


async def _drain_queue(queue: asyncio.Queue) -> list[dict]:
    """Drain all events from a queue into a list."""
    events = []
    while not queue.empty():
        evt = queue.get_nowait()
        if evt is not None:
            events.append(evt)
    return events


def _make_request(**kwargs):
    from models import GenerateRequest
    defaults = dict(
        title="Test Song",
        description="A rock song about testing",
        lyrics="Some test lyrics here",
        duration=3.0,
        include_vocals=True,
        enhance_lyrics=False,
        bpm="",
        key="",
        creativity=50,
        seed="",
    )
    defaults.update(kwargs)
    return GenerateRequest(**defaults)


@pytest.mark.asyncio
async def test_health_check_called_before_submit(patch_outputs):
    """Health check should be called before submitting to ACE-Step."""
    import config

    fake_flac = config.AUDIO_DIR / "test-output.flac"
    fake_flac.write_bytes(b"FLAC")

    health_calls = []

    async def mock_health():
        health_calls.append(1)
        return True

    async def mock_streaming(req, **kwargs):
        yield {"event": "step", "step": "submit", "state": "done"}
        yield {"event": "complete", "result": {
            "file_path": str(fake_flac),
            "filename": "test-output.flac",
            "seed": 42,
        }}

    from main import _run_generation

    queue = asyncio.Queue()
    req = _make_request()

    with patch("gradio_client.check_health", new=mock_health), \
         patch("gradio_client.generate_streaming", new=mock_streaming), \
         patch("cover_art.generate_cover", new=AsyncMock(return_value=None)), \
         patch("validation.validate_track", new=AsyncMock(return_value=None)):
        await _run_generation("job-1", "track-1", "rock", req, queue, "Test Song", False)

    assert len(health_calls) >= 1, "check_health should be called at least once"


@pytest.mark.asyncio
async def test_health_check_retries_on_failure(patch_outputs):
    """When health check fails, it should retry up to 6 times with 30s waits."""
    health_call_count = 0

    async def mock_health_always_fail():
        nonlocal health_call_count
        health_call_count += 1
        return False

    from main import _run_generation

    queue = asyncio.Queue()
    req = _make_request()

    with patch("gradio_client.check_health", new=mock_health_always_fail), \
         patch("asyncio.sleep", new=AsyncMock()):
        await _run_generation("job-2", "track-2", "rock", req, queue, "Test Song", False)

    # Should have tried 6 times (the for range(6) loop)
    assert health_call_count == 6, f"Expected 6 health check attempts, got {health_call_count}"

    # Should have emitted an error event
    events = await _drain_queue(queue)
    error_events = [e for e in events if e.get("event") == "error"]
    assert len(error_events) >= 1, "Should emit an error when health check fails"
    assert "not responding" in error_events[0]["message"].lower() or "ace-step" in error_events[0]["message"].lower()


@pytest.mark.asyncio
async def test_health_check_succeeds_on_third_try(patch_outputs):
    """Health check should pass after failing twice, then proceed to generation."""
    import config

    fake_flac = config.AUDIO_DIR / "retry-output.flac"
    fake_flac.write_bytes(b"FLAC")

    health_call_count = 0

    async def mock_health_third_try():
        nonlocal health_call_count
        health_call_count += 1
        return health_call_count >= 3  # Fail first two, succeed on third

    async def mock_streaming(req, **kwargs):
        yield {"event": "step", "step": "submit", "state": "done"}
        yield {"event": "complete", "result": {
            "file_path": str(fake_flac),
            "filename": "retry-output.flac",
            "seed": 99,
        }}

    from main import _run_generation

    queue = asyncio.Queue()
    req = _make_request()

    with patch("gradio_client.check_health", new=mock_health_third_try), \
         patch("gradio_client.generate_streaming", new=mock_streaming), \
         patch("asyncio.sleep", new=AsyncMock()), \
         patch("cover_art.generate_cover", new=AsyncMock(return_value=None)), \
         patch("validation.validate_track", new=AsyncMock(return_value=None)):
        await _run_generation("job-3", "track-3", "rock", req, queue, "Test Song", False)

    assert health_call_count == 3, f"Expected 3 health checks, got {health_call_count}"

    events = await _drain_queue(queue)
    # Should have a track event (successful generation)
    track_events = [e for e in events if e.get("event") == "track"]
    assert len(track_events) == 1, "Should have created a track after retry"


@pytest.mark.asyncio
async def test_acestep_crash_mid_generation_retry(patch_outputs):
    """When ACE-Step crashes mid-generation, it should wait for restart and retry."""
    import config

    fake_flac = config.AUDIO_DIR / "crash-retry.flac"
    fake_flac.write_bytes(b"FLAC")

    gen_call_count = 0

    async def mock_streaming_crash_then_succeed(req, **kwargs):
        nonlocal gen_call_count
        gen_call_count += 1
        if gen_call_count == 1:
            # First attempt: crash
            yield {"event": "step", "step": "submit", "state": "done"}
            yield {"event": "error", "message": "GPU crashed"}
        else:
            # Second attempt: success
            yield {"event": "step", "step": "submit", "state": "done"}
            yield {"event": "complete", "result": {
                "file_path": str(fake_flac),
                "filename": "crash-retry.flac",
                "seed": 555,
            }}

    # Health check returns True immediately (ACE-Step restarted)
    health_after_crash = 0

    async def mock_health_for_crash():
        nonlocal health_after_crash
        health_after_crash += 1
        return True

    from main import _run_generation

    queue = asyncio.Queue()
    req = _make_request()

    with patch("gradio_client.check_health", new=mock_health_for_crash), \
         patch("gradio_client.generate_streaming", new=mock_streaming_crash_then_succeed), \
         patch("asyncio.sleep", new=AsyncMock()), \
         patch("cover_art.generate_cover", new=AsyncMock(return_value=None)), \
         patch("validation.validate_track", new=AsyncMock(return_value=None)):
        await _run_generation("job-4", "track-4", "rock", req, queue, "Test Song", False)

    assert gen_call_count == 2, f"Expected 2 generation attempts, got {gen_call_count}"

    events = await _drain_queue(queue)
    track_events = [e for e in events if e.get("event") == "track"]
    assert len(track_events) == 1, "Should have saved the track after successful retry"
    assert track_events[0]["track"]["seed"] == 555


@pytest.mark.asyncio
async def test_max_retries_emits_error(patch_outputs):
    """After max retries, an error event should be emitted."""
    async def mock_streaming_always_fail(req, **kwargs):
        yield {"event": "step", "step": "submit", "state": "done"}
        yield {"event": "error", "message": "GPU out of memory"}

    from main import _run_generation

    queue = asyncio.Queue()
    req = _make_request()

    with patch("gradio_client.check_health", new=AsyncMock(return_value=True)), \
         patch("gradio_client.generate_streaming", new=mock_streaming_always_fail), \
         patch("asyncio.sleep", new=AsyncMock()):
        await _run_generation("job-5", "track-5", "rock", req, queue, "Test Song", False)

    events = await _drain_queue(queue)
    error_events = [e for e in events if e.get("event") == "error"]
    assert len(error_events) >= 1, "Should emit error after all retries exhausted"

    # Should NOT have a track event
    track_events = [e for e in events if e.get("event") == "track"]
    assert len(track_events) == 0, "Should not save a track when generation fails"


@pytest.mark.asyncio
async def test_successful_generation_saves_track(patch_outputs):
    """A successful generation (even after initial health check delay) should save the track to history."""
    import config
    import history as h

    fake_flac = config.AUDIO_DIR / "save-test.flac"
    fake_flac.write_bytes(b"FLAC")

    async def mock_streaming(req, **kwargs):
        yield {"event": "step", "step": "submit", "state": "done"}
        yield {"event": "complete", "result": {
            "file_path": str(fake_flac),
            "filename": "save-test.flac",
            "seed": 777,
        }}

    from main import _run_generation

    queue = asyncio.Queue()
    req = _make_request()

    with patch("gradio_client.check_health", new=AsyncMock(return_value=True)), \
         patch("gradio_client.generate_streaming", new=mock_streaming), \
         patch("cover_art.generate_cover", new=AsyncMock(return_value=None)), \
         patch("validation.validate_track", new=AsyncMock(return_value=None)):
        await _run_generation("job-6", "track-6", "rock", req, queue, "Test Song", False)

    # Verify track was saved to history
    tracks = await h.load()
    assert len(tracks) == 1
    assert tracks[0].id == "track-6"
    assert tracks[0].seed == 777


@pytest.mark.asyncio
async def test_generation_exception_emits_error(patch_outputs):
    """An exception during streaming should result in error event."""
    async def mock_streaming_exception(req, **kwargs):
        yield {"event": "step", "step": "submit", "state": "done"}
        raise ConnectionError("Connection reset by peer")

    from main import _run_generation

    queue = asyncio.Queue()
    req = _make_request()

    with patch("gradio_client.check_health", new=AsyncMock(return_value=True)), \
         patch("gradio_client.generate_streaming", new=mock_streaming_exception), \
         patch("asyncio.sleep", new=AsyncMock()):
        await _run_generation("job-7", "track-7", "rock", req, queue, "Test Song", False)

    events = await _drain_queue(queue)
    error_events = [e for e in events if e.get("event") == "error"]
    assert len(error_events) >= 1, "Should emit error when streaming raises exception"
