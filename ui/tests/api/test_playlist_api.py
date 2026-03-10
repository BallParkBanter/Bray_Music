"""Tests for playlist API endpoints."""

import json
import pytest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))


@pytest.fixture(autouse=True)
def patch_playlists_file(patch_outputs, monkeypatch):
    """Redirect PLAYLISTS_FILE to temp directory for each test."""
    import config
    import history as hist_mod

    playlists_file = patch_outputs / "playlists.json"
    monkeypatch.setattr(config, "PLAYLISTS_FILE", playlists_file)
    monkeypatch.setattr(hist_mod, "PLAYLISTS_FILE", playlists_file)
    return playlists_file


# ─── POST /playlists ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_playlist(test_client):
    """Creating a playlist should return the new playlist with an id."""
    resp = await test_client.post("/playlists", json={"name": "My Favorites"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["name"] == "My Favorites"
    assert "id" in data
    assert data["track_ids"] == []
    assert "created_at" in data
    assert "cover_gradient" in data


@pytest.mark.asyncio
async def test_create_playlist_default_name(test_client):
    """Creating a playlist without a name should use default."""
    resp = await test_client.post("/playlists", json={})
    assert resp.status_code == 200
    data = resp.json()
    assert data["name"] == "Untitled Playlist"


# ─── GET /playlists ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_playlists_empty(test_client):
    """Listing playlists when none exist should return empty list."""
    resp = await test_client.get("/playlists")
    assert resp.status_code == 200
    data = resp.json()
    assert data["playlists"] == []
    assert data["total"] == 0


@pytest.mark.asyncio
async def test_list_playlists_populated(test_client):
    """Listing playlists after creating some should return them all."""
    await test_client.post("/playlists", json={"name": "Rock"})
    await test_client.post("/playlists", json={"name": "Jazz"})

    resp = await test_client.get("/playlists")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 2
    names = {p["name"] for p in data["playlists"]}
    assert names == {"Rock", "Jazz"}


# ─── DELETE /playlists/{id} ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_delete_playlist(test_client):
    """Deleting an existing playlist should remove it."""
    create_resp = await test_client.post("/playlists", json={"name": "To Delete"})
    playlist_id = create_resp.json()["id"]

    resp = await test_client.delete(f"/playlists/{playlist_id}")
    assert resp.status_code == 200
    assert resp.json()["status"] == "deleted"

    # Verify it's gone
    list_resp = await test_client.get("/playlists")
    assert list_resp.json()["total"] == 0


@pytest.mark.asyncio
async def test_delete_nonexistent_playlist(test_client):
    """Deleting a playlist that doesn't exist should return 404."""
    resp = await test_client.delete("/playlists/does-not-exist")
    assert resp.status_code == 404


# ─── POST /playlists/{id}/tracks ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_add_track_to_playlist(test_client):
    """Adding a track to a playlist should succeed."""
    create_resp = await test_client.post("/playlists", json={"name": "My Playlist"})
    playlist_id = create_resp.json()["id"]

    resp = await test_client.post(
        f"/playlists/{playlist_id}/tracks",
        json={"track_id": "track-123"}
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "added"

    # Verify the track is in the playlist
    list_resp = await test_client.get("/playlists")
    playlists = list_resp.json()["playlists"]
    playlist = next(p for p in playlists if p["id"] == playlist_id)
    assert "track-123" in playlist["track_ids"]


@pytest.mark.asyncio
async def test_add_duplicate_track_to_playlist(test_client):
    """Adding the same track twice should not create a duplicate."""
    create_resp = await test_client.post("/playlists", json={"name": "No Dupes"})
    playlist_id = create_resp.json()["id"]

    await test_client.post(
        f"/playlists/{playlist_id}/tracks",
        json={"track_id": "track-dup"}
    )
    await test_client.post(
        f"/playlists/{playlist_id}/tracks",
        json={"track_id": "track-dup"}
    )

    list_resp = await test_client.get("/playlists")
    playlists = list_resp.json()["playlists"]
    playlist = next(p for p in playlists if p["id"] == playlist_id)
    assert playlist["track_ids"].count("track-dup") == 1


@pytest.mark.asyncio
async def test_add_track_to_nonexistent_playlist(test_client):
    """Adding a track to a nonexistent playlist should return 404."""
    resp = await test_client.post(
        "/playlists/nonexistent/tracks",
        json={"track_id": "track-123"}
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_add_track_missing_track_id(test_client):
    """Adding without track_id should return 400."""
    create_resp = await test_client.post("/playlists", json={"name": "Test"})
    playlist_id = create_resp.json()["id"]

    resp = await test_client.post(
        f"/playlists/{playlist_id}/tracks",
        json={}
    )
    assert resp.status_code == 400


# ─── DELETE /playlists/{id}/tracks/{track_id} ────────────────────────────────


@pytest.mark.asyncio
async def test_remove_track_from_playlist(test_client):
    """Removing a track from a playlist should succeed."""
    create_resp = await test_client.post("/playlists", json={"name": "Remove Test"})
    playlist_id = create_resp.json()["id"]

    await test_client.post(
        f"/playlists/{playlist_id}/tracks",
        json={"track_id": "track-to-remove"}
    )

    resp = await test_client.delete(f"/playlists/{playlist_id}/tracks/track-to-remove")
    assert resp.status_code == 200
    assert resp.json()["status"] == "removed"

    # Verify it's gone
    list_resp = await test_client.get("/playlists")
    playlists = list_resp.json()["playlists"]
    playlist = next(p for p in playlists if p["id"] == playlist_id)
    assert "track-to-remove" not in playlist["track_ids"]


@pytest.mark.asyncio
async def test_remove_track_from_nonexistent_playlist(test_client):
    """Removing from a nonexistent playlist should return 404."""
    resp = await test_client.delete("/playlists/nonexistent/tracks/track-123")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_remove_nonexistent_track_from_playlist(test_client):
    """Removing a track that's not in the playlist should return 404."""
    create_resp = await test_client.post("/playlists", json={"name": "Test"})
    playlist_id = create_resp.json()["id"]

    resp = await test_client.delete(f"/playlists/{playlist_id}/tracks/no-such-track")
    assert resp.status_code == 404
