import asyncio
import json
import pytest
import pytest_asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))


@pytest.mark.asyncio
async def test_append_creates_file(patch_outputs, sample_track):
    import config
    import history as h

    assert not config.HISTORY_FILE.exists()
    await h.append(sample_track)
    assert config.HISTORY_FILE.exists()
    data = json.loads(config.HISTORY_FILE.read_text())
    assert len(data) == 1
    assert data[0]["id"] == sample_track.id


@pytest.mark.asyncio
async def test_append_preserves_existing(patch_outputs, sample_track):
    import history as h
    from models import TrackMeta
    import copy

    track2 = sample_track.model_copy(update={"id": "track-2", "title": "Second Song"})
    await h.append(sample_track)
    await h.append(track2)

    tracks = await h.load()
    assert len(tracks) == 2
    ids = {t.id for t in tracks}
    assert sample_track.id in ids
    assert "track-2" in ids


@pytest.mark.asyncio
async def test_remove_existing(patch_outputs, sample_track):
    import history as h

    await h.append(sample_track)
    result = await h.remove(sample_track.id)
    assert result is True
    tracks = await h.load()
    assert len(tracks) == 0


@pytest.mark.asyncio
async def test_remove_nonexistent(patch_outputs):
    import history as h

    result = await h.remove("does-not-exist")
    assert result is False


@pytest.mark.asyncio
async def test_update_cover(patch_outputs, sample_track):
    import history as h

    await h.append(sample_track)
    await h.update_cover(sample_track.id, "mycover.png")

    track = await h.get(sample_track.id)
    assert track is not None
    assert track.cover_art == "mycover.png"


@pytest.mark.asyncio
async def test_concurrent_writes(patch_outputs):
    import history as h
    from models import TrackMeta

    tracks = [
        TrackMeta(
            id=f"track-{i}",
            title=f"Song {i}",
            description="desc",
            duration_sec=180.0,
            filename=f"track-{i}.flac",
            created_at="2026-03-03T10:00:00+00:00",
        )
        for i in range(10)
    ]

    await asyncio.gather(*[h.append(t) for t in tracks])

    loaded = await h.load()
    assert len(loaded) == 10
