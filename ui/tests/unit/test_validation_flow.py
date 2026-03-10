"""Tests for the _bg_validate_and_cover() post-processing logic in main.py."""

import asyncio
import pytest
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch, MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from models import TrackMeta


def _make_track(**kwargs) -> TrackMeta:
    """Create a TrackMeta with sensible defaults for testing."""
    defaults = dict(
        id="test-track-001",
        title="Test Song",
        description="A rock song about testing",
        genre_hint="rock",
        duration_sec=180.0,
        filename="test-track-001.flac",
        cover_art=None,
        cover_gradient="linear-gradient(135deg, #667eea 0%, #764ba2 100%)",
        emoji="🎸",
        created_at="2026-03-03T10:00:00+00:00",
        seed=42,
        lyrics="",
        include_vocals=True,
    )
    defaults.update(kwargs)
    return TrackMeta(**defaults)


async def _drain_queue(queue: asyncio.Queue) -> list[dict]:
    """Drain all events from a queue."""
    events = []
    while not queue.empty():
        evt = queue.get_nowait()
        if evt is not None:
            events.append(evt)
    return events


# ─── Vocal vs Instrumental ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_vocal_tracks_get_whisper_validation(patch_outputs):
    """Vocal tracks (with real lyrics) should be sent to Whisper validation."""
    from main import _bg_validate_and_cover

    track = _make_track(lyrics="Some real lyrics here")
    queue = asyncio.Queue()

    mock_validate = AsyncMock(return_value={
        "quality_score": 0.85,
        "quality_rating": "GREAT",
        "segments": 10,
        "good_segments": 9,
    })

    with patch("validation.validate_track", new=mock_validate), \
         patch("cover_art.generate_cover", new=AsyncMock(return_value="test.png")), \
         patch("history.update_quality", new=AsyncMock()), \
         patch("history.update_cover", new=AsyncMock()):
        await _bg_validate_and_cover(track, queue=queue)

    mock_validate.assert_called_once_with(track.filename)


@pytest.mark.asyncio
async def test_instrumental_tracks_skip_validation(patch_outputs):
    """Instrumental tracks should skip Whisper validation entirely."""
    from main import _bg_validate_and_cover

    track = _make_track(lyrics="[Instrumental]")
    queue = asyncio.Queue()

    mock_validate = AsyncMock()

    with patch("validation.validate_track", new=mock_validate), \
         patch("cover_art.generate_cover", new=AsyncMock(return_value="test.png")), \
         patch("history.update_cover", new=AsyncMock()):
        await _bg_validate_and_cover(track, queue=queue)

    mock_validate.assert_not_called()


@pytest.mark.asyncio
async def test_instrumental_empty_lyrics_skip_validation(patch_outputs):
    """Tracks with empty lyrics should be treated as instrumental."""
    from main import _bg_validate_and_cover

    track = _make_track(lyrics="")
    queue = asyncio.Queue()

    mock_validate = AsyncMock()

    with patch("validation.validate_track", new=mock_validate), \
         patch("cover_art.generate_cover", new=AsyncMock(return_value="test.png")), \
         patch("history.update_cover", new=AsyncMock()):
        await _bg_validate_and_cover(track, queue=queue)

    mock_validate.assert_not_called()


# ─── Quality → Cover Art Logic ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_good_quality_gets_ai_cover(patch_outputs):
    """GOOD quality rating should trigger AI cover art generation."""
    from main import _bg_validate_and_cover

    track = _make_track(lyrics="Real lyrics for vocal track")
    queue = asyncio.Queue()

    mock_cover = AsyncMock(return_value="cover.png")

    with patch("validation.validate_track", new=AsyncMock(return_value={
            "quality_score": 0.7, "quality_rating": "GOOD",
         })), \
         patch("cover_art.generate_cover", new=mock_cover), \
         patch("history.update_quality", new=AsyncMock()), \
         patch("history.update_cover", new=AsyncMock()):
        await _bg_validate_and_cover(track, queue=queue)

    mock_cover.assert_called_once()


@pytest.mark.asyncio
async def test_great_quality_gets_ai_cover(patch_outputs):
    """GREAT quality rating should trigger AI cover art generation."""
    from main import _bg_validate_and_cover

    track = _make_track(lyrics="Real lyrics for great track")
    queue = asyncio.Queue()

    mock_cover = AsyncMock(return_value="cover.png")

    with patch("validation.validate_track", new=AsyncMock(return_value={
            "quality_score": 0.9, "quality_rating": "GREAT",
         })), \
         patch("cover_art.generate_cover", new=mock_cover), \
         patch("history.update_quality", new=AsyncMock()), \
         patch("history.update_cover", new=AsyncMock()):
        await _bg_validate_and_cover(track, queue=queue)

    mock_cover.assert_called_once()


@pytest.mark.asyncio
async def test_fair_quality_skips_ai_cover(patch_outputs):
    """FAIR quality rating should skip AI cover art (gradient only)."""
    from main import _bg_validate_and_cover

    track = _make_track(lyrics="Real lyrics but poor quality")
    queue = asyncio.Queue()

    mock_cover = AsyncMock(return_value="cover.png")

    with patch("validation.validate_track", new=AsyncMock(return_value={
            "quality_score": 0.4, "quality_rating": "FAIR",
         })), \
         patch("cover_art.generate_cover", new=mock_cover), \
         patch("history.update_quality", new=AsyncMock()):
        await _bg_validate_and_cover(track, queue=queue)

    mock_cover.assert_not_called()


@pytest.mark.asyncio
async def test_poor_quality_skips_ai_cover(patch_outputs):
    """POOR quality rating should skip AI cover art (gradient only)."""
    from main import _bg_validate_and_cover

    track = _make_track(lyrics="Real lyrics but terrible quality")
    queue = asyncio.Queue()

    mock_cover = AsyncMock(return_value="cover.png")

    with patch("validation.validate_track", new=AsyncMock(return_value={
            "quality_score": 0.2, "quality_rating": "POOR",
         })), \
         patch("cover_art.generate_cover", new=mock_cover), \
         patch("history.update_quality", new=AsyncMock()):
        await _bg_validate_and_cover(track, queue=queue)

    mock_cover.assert_not_called()


@pytest.mark.asyncio
async def test_validation_failure_still_generates_cover(patch_outputs):
    """When validation returns None (service down), cover should still generate."""
    from main import _bg_validate_and_cover

    track = _make_track(lyrics="Real lyrics but validation fails")
    queue = asyncio.Queue()

    mock_cover = AsyncMock(return_value="fallback-cover.png")

    with patch("validation.validate_track", new=AsyncMock(return_value=None)), \
         patch("cover_art.generate_cover", new=mock_cover), \
         patch("history.update_cover", new=AsyncMock()):
        await _bg_validate_and_cover(track, queue=queue)

    # quality_rating is None, so should_generate_cover is True
    mock_cover.assert_called_once()


@pytest.mark.asyncio
async def test_validation_exception_still_generates_cover(patch_outputs):
    """When validation raises an exception, cover should still generate."""
    from main import _bg_validate_and_cover

    track = _make_track(lyrics="Real lyrics but validation crashes")
    queue = asyncio.Queue()

    mock_cover = AsyncMock(return_value="fallback-cover.png")

    with patch("validation.validate_track", new=AsyncMock(side_effect=ConnectionError("timeout"))), \
         patch("cover_art.generate_cover", new=mock_cover), \
         patch("history.update_cover", new=AsyncMock()):
        await _bg_validate_and_cover(track, queue=queue)

    mock_cover.assert_called_once()


# ─── AI Title Generation ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_ai_title_generated_when_needed(patch_outputs):
    """When needs_ai_title=True, generate_title should be called."""
    from main import _bg_validate_and_cover

    track = _make_track(lyrics="[Instrumental]")
    queue = asyncio.Queue()

    mock_title = AsyncMock(return_value="Beautiful Sunrise")

    with patch("lyrics_gen.generate_title", new=mock_title), \
         patch("cover_art.generate_cover", new=AsyncMock(return_value=None)), \
         patch("history.update_title", new=AsyncMock()):
        await _bg_validate_and_cover(track, queue=queue, needs_ai_title=True)

    mock_title.assert_called_once_with(track.description)

    events = await _drain_queue(queue)
    title_events = [e for e in events if e.get("event") == "title"]
    assert len(title_events) == 1
    assert title_events[0]["title"] == "Beautiful Sunrise"


@pytest.mark.asyncio
async def test_ai_title_not_called_when_not_needed(patch_outputs):
    """When needs_ai_title=False, generate_title should NOT be called."""
    from main import _bg_validate_and_cover

    track = _make_track(lyrics="[Instrumental]")
    queue = asyncio.Queue()

    mock_title = AsyncMock(return_value="Should Not Be Called")

    with patch("lyrics_gen.generate_title", new=mock_title), \
         patch("cover_art.generate_cover", new=AsyncMock(return_value=None)):
        await _bg_validate_and_cover(track, queue=queue, needs_ai_title=False)

    mock_title.assert_not_called()


# ─── SSE Events ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_sse_events_for_vocal_validation(patch_outputs):
    """Vocal track should emit validate step events and quality event."""
    from main import _bg_validate_and_cover

    track = _make_track(lyrics="Lyrics for vocal track")
    queue = asyncio.Queue()

    with patch("validation.validate_track", new=AsyncMock(return_value={
            "quality_score": 0.85, "quality_rating": "GREAT",
         })), \
         patch("cover_art.generate_cover", new=AsyncMock(return_value="cover.png")), \
         patch("history.update_quality", new=AsyncMock()), \
         patch("history.update_cover", new=AsyncMock()):
        await _bg_validate_and_cover(track, queue=queue)

    events = await _drain_queue(queue)

    # Should have validate step events
    validate_steps = [e for e in events if e.get("event") == "step" and e.get("step") == "validate"]
    assert len(validate_steps) >= 1, "Should have validate step events"

    # Should have quality event
    quality_events = [e for e in events if e.get("event") == "quality"]
    assert len(quality_events) == 1
    assert quality_events[0]["rating"] == "GREAT"

    # Should have cover step events
    cover_steps = [e for e in events if e.get("event") == "step" and e.get("step") == "cover"]
    assert len(cover_steps) >= 1

    # Should have done event
    done_events = [e for e in events if e.get("event") == "done"]
    assert len(done_events) == 1


@pytest.mark.asyncio
async def test_sse_events_for_instrumental(patch_outputs):
    """Instrumental track should skip validate step but still emit cover and done."""
    from main import _bg_validate_and_cover

    track = _make_track(lyrics="")
    queue = asyncio.Queue()

    with patch("cover_art.generate_cover", new=AsyncMock(return_value="cover.png")), \
         patch("history.update_cover", new=AsyncMock()):
        await _bg_validate_and_cover(track, queue=queue)

    events = await _drain_queue(queue)

    # Should NOT have validate step events
    validate_steps = [e for e in events if e.get("event") == "step" and e.get("step") == "validate"]
    assert len(validate_steps) == 0

    # Should have cover and done events
    cover_steps = [e for e in events if e.get("event") == "step" and e.get("step") == "cover"]
    assert len(cover_steps) >= 1
    done_events = [e for e in events if e.get("event") == "done"]
    assert len(done_events) == 1


@pytest.mark.asyncio
async def test_sse_cover_art_event_emitted(patch_outputs):
    """When cover art is generated, a cover_art event should be emitted."""
    from main import _bg_validate_and_cover

    track = _make_track(lyrics="[Instrumental]")
    queue = asyncio.Queue()

    with patch("cover_art.generate_cover", new=AsyncMock(return_value="my-cover.png")), \
         patch("history.update_cover", new=AsyncMock()):
        await _bg_validate_and_cover(track, queue=queue)

    events = await _drain_queue(queue)
    cover_events = [e for e in events if e.get("event") == "cover_art"]
    assert len(cover_events) == 1
    assert cover_events[0]["cover_art"] == "my-cover.png"


@pytest.mark.asyncio
async def test_no_queue_does_not_crash(patch_outputs):
    """When queue is None (non-streaming mode), _bg_validate_and_cover should not crash."""
    from main import _bg_validate_and_cover

    track = _make_track(lyrics="[Instrumental]")

    with patch("cover_art.generate_cover", new=AsyncMock(return_value="cover.png")), \
         patch("history.update_cover", new=AsyncMock()):
        # Should not raise
        await _bg_validate_and_cover(track, queue=None)
