"""Tests for favorites toggle and history filter/sort endpoints."""

import json
import pytest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))


async def _add_test_tracks(h):
    """Add a mix of vocal, instrumental, and favorited tracks."""
    from models import TrackMeta

    tracks = [
        TrackMeta(
            id="vocal-1", title="Vocal Song", description="A pop song",
            genre_hint="pop", duration_sec=180.0, filename="vocal-1.flac",
            lyrics="Some real lyrics here", favorite=False,
            created_at="2026-03-01T10:00:00+00:00",
        ),
        TrackMeta(
            id="vocal-2", title="Another Vocal", description="A rock song",
            genre_hint="rock", duration_sec=200.0, filename="vocal-2.flac",
            lyrics="More lyrics", favorite=True,
            created_at="2026-03-02T10:00:00+00:00",
        ),
        TrackMeta(
            id="inst-1", title="Instrumental Piece", description="An ambient track",
            genre_hint="ambient", duration_sec=240.0, filename="inst-1.flac",
            lyrics="", favorite=False,
            created_at="2026-03-03T10:00:00+00:00",
        ),
        TrackMeta(
            id="inst-2", title="Chill Beats", description="lofi beats",
            genre_hint="ambient", duration_sec=300.0, filename="inst-2.flac",
            lyrics="[Instrumental]", favorite=True,
            created_at="2026-03-04T10:00:00+00:00",
        ),
    ]
    for t in tracks:
        await h.append(t)
    return tracks


# ─── POST /track/{id}/favorite ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_toggle_favorite_on(test_client, patch_outputs):
    """Toggling favorite on an unfavorited track should set favorite=True."""
    import history as h

    await _add_test_tracks(h)

    resp = await test_client.post("/track/vocal-1/favorite")
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == "vocal-1"
    assert data["favorite"] is True


@pytest.mark.asyncio
async def test_toggle_favorite_off(test_client, patch_outputs):
    """Toggling favorite on an already-favorited track should set favorite=False."""
    import history as h

    await _add_test_tracks(h)

    # vocal-2 is already favorited
    resp = await test_client.post("/track/vocal-2/favorite")
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == "vocal-2"
    assert data["favorite"] is False


@pytest.mark.asyncio
async def test_toggle_favorite_nonexistent(test_client, patch_outputs):
    """Toggling favorite on a nonexistent track should return 404."""
    resp = await test_client.post("/track/nonexistent/favorite")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_toggle_favorite_double(test_client, patch_outputs):
    """Toggling favorite twice should return to original state."""
    import history as h

    await _add_test_tracks(h)

    # vocal-1 starts unfavorited
    await test_client.post("/track/vocal-1/favorite")  # -> True
    resp = await test_client.post("/track/vocal-1/favorite")  # -> False
    assert resp.json()["favorite"] is False


# ─── GET /history?filter=favorites ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_filter_favorites(test_client, patch_outputs):
    """Filter=favorites should return only favorited tracks."""
    import history as h

    await _add_test_tracks(h)

    resp = await test_client.get("/history?filter=favorites")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 2
    ids = {t["id"] for t in data["tracks"]}
    assert ids == {"vocal-2", "inst-2"}


# ─── GET /history?filter=instrumental ────────────────────────────────────────


@pytest.mark.asyncio
async def test_filter_instrumental(test_client, patch_outputs):
    """Filter=instrumental should return tracks with no lyrics or [Instrumental]."""
    import history as h

    await _add_test_tracks(h)

    resp = await test_client.get("/history?filter=instrumental")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 2
    ids = {t["id"] for t in data["tracks"]}
    assert ids == {"inst-1", "inst-2"}


# ─── GET /history?filter=vocals ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_filter_vocals(test_client, patch_outputs):
    """Filter=vocals should return only tracks with real lyrics."""
    import history as h

    await _add_test_tracks(h)

    resp = await test_client.get("/history?filter=vocals")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 2
    ids = {t["id"] for t in data["tracks"]}
    assert ids == {"vocal-1", "vocal-2"}


# ─── GET /history?sort=oldest ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_sort_oldest(test_client, patch_outputs):
    """Sort=oldest should return tracks in ascending date order."""
    import history as h

    await _add_test_tracks(h)

    resp = await test_client.get("/history?sort=oldest")
    assert resp.status_code == 200
    data = resp.json()
    titles = [t["title"] for t in data["tracks"]]
    assert titles == ["Vocal Song", "Another Vocal", "Instrumental Piece", "Chill Beats"]


@pytest.mark.asyncio
async def test_sort_newest(test_client, patch_outputs):
    """Sort=newest should return tracks in descending date order."""
    import history as h

    await _add_test_tracks(h)

    resp = await test_client.get("/history?sort=newest")
    assert resp.status_code == 200
    data = resp.json()
    titles = [t["title"] for t in data["tracks"]]
    assert titles == ["Chill Beats", "Instrumental Piece", "Another Vocal", "Vocal Song"]


# ─── Filter + Search combinations ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_filter_favorites_with_search(test_client, patch_outputs):
    """Filter=favorites combined with search should narrow results further."""
    import history as h

    await _add_test_tracks(h)

    resp = await test_client.get("/history?filter=favorites&search=vocal")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 1
    assert data["tracks"][0]["id"] == "vocal-2"


@pytest.mark.asyncio
async def test_filter_instrumental_with_search(test_client, patch_outputs):
    """Filter=instrumental combined with search should narrow results."""
    import history as h

    await _add_test_tracks(h)

    resp = await test_client.get("/history?filter=instrumental&search=chill")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 1
    assert data["tracks"][0]["id"] == "inst-2"


@pytest.mark.asyncio
async def test_filter_with_no_matches(test_client, patch_outputs):
    """Filter + search with no matching results should return empty."""
    import history as h

    await _add_test_tracks(h)

    resp = await test_client.get("/history?filter=favorites&search=nonexistent")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 0
    assert data["tracks"] == []
