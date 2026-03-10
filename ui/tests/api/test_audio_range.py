"""Tests for audio range request handling (HTTP 206 Partial Content)."""

import pytest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))


def _create_fake_flac(audio_dir: Path, filename: str = "range-test.flac", size: int = 4096) -> Path:
    """Create a fake FLAC file with known content for range testing."""
    flac = audio_dir / filename
    # Write sequential bytes so we can verify range content
    content = bytes(range(256)) * (size // 256) + bytes(range(size % 256))
    flac.write_bytes(content[:size])
    return flac


# ─── Full File Download ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_full_file_download(test_client, patch_outputs):
    """Requesting audio without Range header should return full file (200)."""
    import config

    flac = _create_fake_flac(config.AUDIO_DIR, size=2048)

    resp = await test_client.get("/audio/range-test.flac")
    assert resp.status_code == 200
    assert len(resp.content) == 2048


@pytest.mark.asyncio
async def test_full_download_has_accept_ranges(test_client, patch_outputs):
    """Full download response should include Accept-Ranges: bytes header."""
    import config

    _create_fake_flac(config.AUDIO_DIR, size=1024)

    resp = await test_client.get("/audio/range-test.flac")
    assert resp.status_code == 200
    assert resp.headers.get("accept-ranges") == "bytes"


@pytest.mark.asyncio
async def test_full_download_content_type(test_client, patch_outputs):
    """Full download should have audio/flac content type."""
    import config

    _create_fake_flac(config.AUDIO_DIR, size=512)

    resp = await test_client.get("/audio/range-test.flac")
    assert "audio" in resp.headers.get("content-type", "")


# ─── Partial Content (206) ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_range_first_1024_bytes(test_client, patch_outputs):
    """Range: bytes=0-1023 should return first 1024 bytes with 206."""
    import config

    _create_fake_flac(config.AUDIO_DIR, size=4096)

    resp = await test_client.get(
        "/audio/range-test.flac",
        headers={"Range": "bytes=0-1023"}
    )
    assert resp.status_code == 206
    assert len(resp.content) == 1024
    assert resp.headers.get("content-length") == "1024"


@pytest.mark.asyncio
async def test_range_content_range_header(test_client, patch_outputs):
    """Partial content should include correct Content-Range header."""
    import config

    _create_fake_flac(config.AUDIO_DIR, size=4096)

    resp = await test_client.get(
        "/audio/range-test.flac",
        headers={"Range": "bytes=0-1023"}
    )
    assert resp.status_code == 206
    content_range = resp.headers.get("content-range", "")
    assert content_range == "bytes 0-1023/4096"


@pytest.mark.asyncio
async def test_range_middle_bytes(test_client, patch_outputs):
    """Range for middle portion of file should return correct bytes."""
    import config

    _create_fake_flac(config.AUDIO_DIR, size=4096)

    resp = await test_client.get(
        "/audio/range-test.flac",
        headers={"Range": "bytes=1024-2047"}
    )
    assert resp.status_code == 206
    assert len(resp.content) == 1024
    content_range = resp.headers.get("content-range", "")
    assert content_range == "bytes 1024-2047/4096"


@pytest.mark.asyncio
async def test_range_open_ended(test_client, patch_outputs):
    """Range: bytes=1024- (open-ended) should return from offset to end."""
    import config

    _create_fake_flac(config.AUDIO_DIR, size=4096)

    resp = await test_client.get(
        "/audio/range-test.flac",
        headers={"Range": "bytes=1024-"}
    )
    assert resp.status_code == 206
    assert len(resp.content) == 3072  # 4096 - 1024
    content_range = resp.headers.get("content-range", "")
    assert content_range == "bytes 1024-4095/4096"


@pytest.mark.asyncio
async def test_range_accept_ranges_header(test_client, patch_outputs):
    """Partial content response should include Accept-Ranges: bytes."""
    import config

    _create_fake_flac(config.AUDIO_DIR, size=4096)

    resp = await test_client.get(
        "/audio/range-test.flac",
        headers={"Range": "bytes=0-511"}
    )
    assert resp.status_code == 206
    assert resp.headers.get("accept-ranges") == "bytes"


@pytest.mark.asyncio
async def test_range_last_bytes(test_client, patch_outputs):
    """Range requesting last few bytes should work correctly."""
    import config

    _create_fake_flac(config.AUDIO_DIR, size=4096)

    resp = await test_client.get(
        "/audio/range-test.flac",
        headers={"Range": "bytes=4000-4095"}
    )
    assert resp.status_code == 206
    assert len(resp.content) == 96
    content_range = resp.headers.get("content-range", "")
    assert content_range == "bytes 4000-4095/4096"


# ─── Edge Cases ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_audio_not_found(test_client, patch_outputs):
    """Requesting nonexistent audio should return 404."""
    resp = await test_client.get("/audio/nonexistent.flac")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_range_single_byte(test_client, patch_outputs):
    """Range requesting a single byte should work."""
    import config

    _create_fake_flac(config.AUDIO_DIR, size=4096)

    resp = await test_client.get(
        "/audio/range-test.flac",
        headers={"Range": "bytes=0-0"}
    )
    assert resp.status_code == 206
    assert len(resp.content) == 1
    assert resp.headers.get("content-length") == "1"
