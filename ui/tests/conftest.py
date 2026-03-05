import json
import os
import sys
import pytest
import pytest_asyncio
from pathlib import Path

# Add ui/ to path so imports work
sys.path.insert(0, str(Path(__file__).parent.parent))


@pytest.fixture(autouse=True)
def patch_outputs(tmp_path, monkeypatch):
    """Redirect all file paths to a temp directory for each test."""
    import config
    covers = tmp_path / "covers"
    audio = tmp_path / "api_audio"
    covers.mkdir()
    audio.mkdir()
    history = tmp_path / "history.json"

    # Patch config module
    monkeypatch.setattr(config, "OUTPUTS_DIR", tmp_path)
    monkeypatch.setattr(config, "COVERS_DIR", covers)
    monkeypatch.setattr(config, "AUDIO_DIR", audio)
    monkeypatch.setattr(config, "HISTORY_FILE", history)

    # Patch history module's imported reference
    import history as hist_mod
    monkeypatch.setattr(hist_mod, "HISTORY_FILE", history)

    # Patch cover_art module's imported reference
    import cover_art as ca_mod
    monkeypatch.setattr(ca_mod, "COVERS_DIR", covers)

    # Patch main module's imported references
    import main as main_mod
    monkeypatch.setattr(main_mod, "AUDIO_DIR", audio)
    monkeypatch.setattr(main_mod, "COVERS_DIR", covers)
    monkeypatch.setattr(main_mod, "OUTPUTS_DIR", tmp_path)

    return tmp_path


@pytest.fixture
def sample_track():
    from models import TrackMeta
    return TrackMeta(
        id="test-id-1234",
        title="Test Song",
        description="A test rock song",
        genre_hint="rock",
        duration_sec=180.0,
        filename="test-id-1234.flac",
        cover_art=None,
        cover_gradient="linear-gradient(135deg,#667eea 0%,#764ba2 100%)",
        emoji="🎸",
        created_at="2026-03-03T10:00:00+00:00",
        seed=42,
    )


@pytest_asyncio.fixture
async def test_client(patch_outputs):
    from httpx import AsyncClient, ASGITransport
    from main import app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client
