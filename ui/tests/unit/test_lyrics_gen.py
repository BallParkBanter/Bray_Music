"""Tests for lyrics generation via Ollama (lyrics_gen.py)."""

import pytest
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch, MagicMock

import httpx

sys.path.insert(0, str(Path(__file__).parent.parent.parent))


# ─── Genre → Prompt Template Selection ──────────────────────────────────────


@pytest.mark.asyncio
async def test_rap_genre_uses_rap_template():
    """Hip hop genre should use LYRICS_PROMPT_RAP template."""
    import lyrics_gen

    captured_prompt = None

    async def mock_post(self, url, **kwargs):
        nonlocal captured_prompt
        captured_prompt = kwargs.get("json", {}).get("prompt", "")
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {"response": "[Verse 1]\nSome rap lyrics here that are long enough to pass validation"}
        resp.raise_for_status = MagicMock()
        return resp

    with patch("lyrics_gen.ensure_model_loaded", new=AsyncMock(return_value=False)), \
         patch.object(httpx.AsyncClient, "post", new=mock_post):
        result = await lyrics_gen.generate_lyrics("a hard-hitting rap track", genre="hip hop")

    assert captured_prompt is not None
    assert "elite rap songwriter" in captured_prompt
    assert "16 bars" in captured_prompt


@pytest.mark.asyncio
async def test_ballad_genre_uses_ballad_template():
    """Ballad genre should use LYRICS_PROMPT_BALLAD template."""
    import lyrics_gen

    captured_prompt = None

    async def mock_post(self, url, **kwargs):
        nonlocal captured_prompt
        captured_prompt = kwargs.get("json", {}).get("prompt", "")
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {"response": "[Verse 1]\nSome ballad lyrics that are long enough to be valid"}
        resp.raise_for_status = MagicMock()
        return resp

    with patch("lyrics_gen.ensure_model_loaded", new=AsyncMock(return_value=False)), \
         patch.object(httpx.AsyncClient, "post", new=mock_post):
        result = await lyrics_gen.generate_lyrics("a slow love song", genre="ballad")

    assert captured_prompt is not None
    assert "emotional ballads" in captured_prompt
    assert "8 lines" in captured_prompt


@pytest.mark.asyncio
async def test_gospel_genre_uses_ballad_template():
    """Gospel genre should also use LYRICS_PROMPT_BALLAD template."""
    import lyrics_gen

    captured_prompt = None

    async def mock_post(self, url, **kwargs):
        nonlocal captured_prompt
        captured_prompt = kwargs.get("json", {}).get("prompt", "")
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {"response": "[Verse 1]\nSome gospel lyrics that are long enough to be valid"}
        resp.raise_for_status = MagicMock()
        return resp

    with patch("lyrics_gen.ensure_model_loaded", new=AsyncMock(return_value=False)), \
         patch.object(httpx.AsyncClient, "post", new=mock_post):
        result = await lyrics_gen.generate_lyrics("an uplifting worship song", genre="gospel")

    assert captured_prompt is not None
    assert "emotional ballads" in captured_prompt


@pytest.mark.asyncio
async def test_unknown_genre_uses_default_template():
    """Unknown genre should use LYRICS_PROMPT_DEFAULT template."""
    import lyrics_gen

    captured_prompt = None

    async def mock_post(self, url, **kwargs):
        nonlocal captured_prompt
        captured_prompt = kwargs.get("json", {}).get("prompt", "")
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {"response": "[Verse 1]\nSome default lyrics that are long enough to validate"}
        resp.raise_for_status = MagicMock()
        return resp

    with patch("lyrics_gen.ensure_model_loaded", new=AsyncMock(return_value=False)), \
         patch.object(httpx.AsyncClient, "post", new=mock_post):
        result = await lyrics_gen.generate_lyrics("a funky groove track", genre="funk")

    assert captured_prompt is not None
    assert "professional songwriter" in captured_prompt
    assert "6 lines" in captured_prompt


# ─── Edge Cases ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_empty_description_returns_none():
    """Empty description should return None immediately without calling Ollama."""
    import lyrics_gen

    mock_ensure = AsyncMock()

    with patch("lyrics_gen.ensure_model_loaded", new=mock_ensure):
        result = await lyrics_gen.generate_lyrics("")

    assert result is None
    mock_ensure.assert_not_called()


@pytest.mark.asyncio
async def test_whitespace_description_returns_none():
    """Whitespace-only description should return None."""
    import lyrics_gen

    mock_ensure = AsyncMock()

    with patch("lyrics_gen.ensure_model_loaded", new=mock_ensure):
        result = await lyrics_gen.generate_lyrics("   ")

    assert result is None
    mock_ensure.assert_not_called()


# ─── ensure_model_loaded ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_ensure_model_returns_false_when_already_loaded():
    """ensure_model_loaded returns False when model is already in GPU."""
    import lyrics_gen

    async def mock_get(self, url, **kwargs):
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {
            "models": [{"name": "gemma3:12b", "size": 1000}]
        }
        return resp

    with patch.object(httpx.AsyncClient, "get", new=mock_get):
        result = await lyrics_gen.ensure_model_loaded()

    assert result is False


@pytest.mark.asyncio
async def test_ensure_model_returns_true_when_cold_start():
    """ensure_model_loaded returns True when model needs to be loaded."""
    import lyrics_gen

    call_count = 0

    async def mock_get(self, url, **kwargs):
        nonlocal call_count
        call_count += 1
        resp = MagicMock()
        resp.status_code = 200
        if call_count == 1:
            # First check: model not loaded
            resp.json.return_value = {"models": []}
        else:
            # After loading: model present
            resp.json.return_value = {
                "models": [{"name": "gemma3:12b", "size": 1000}]
            }
        return resp

    async def mock_post(self, url, **kwargs):
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {"response": ""}
        resp.raise_for_status = MagicMock()
        return resp

    with patch.object(httpx.AsyncClient, "get", new=mock_get), \
         patch.object(httpx.AsyncClient, "post", new=mock_post):
        result = await lyrics_gen.ensure_model_loaded()

    assert result is True


# ─── generate_lyrics calls ensure_model_loaded ──────────────────────────────


@pytest.mark.asyncio
async def test_generate_lyrics_calls_ensure_model():
    """generate_lyrics should call ensure_model_loaded before generating."""
    import lyrics_gen

    ensure_called = False

    async def mock_ensure(model="gemma3:12b"):
        nonlocal ensure_called
        ensure_called = True
        return False

    async def mock_post(self, url, **kwargs):
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {"response": "[Verse 1]\nLyrics that are long enough to pass the length check"}
        resp.raise_for_status = MagicMock()
        return resp

    with patch("lyrics_gen.ensure_model_loaded", new=mock_ensure), \
         patch.object(httpx.AsyncClient, "post", new=mock_post):
        await lyrics_gen.generate_lyrics("A pop song about summer", genre="pop")

    assert ensure_called is True


# ─── Timeout Handling ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_timeout_returns_none():
    """When Ollama times out, generate_lyrics should return None."""
    import lyrics_gen

    async def mock_post(self, url, **kwargs):
        raise httpx.TimeoutException("Connection timed out")

    with patch("lyrics_gen.ensure_model_loaded", new=AsyncMock(return_value=False)), \
         patch.object(httpx.AsyncClient, "post", new=mock_post):
        result = await lyrics_gen.generate_lyrics("A song description", genre="pop")

    assert result is None


@pytest.mark.asyncio
async def test_connection_error_returns_none():
    """When Ollama is unreachable, generate_lyrics should return None."""
    import lyrics_gen

    async def mock_post(self, url, **kwargs):
        raise httpx.ConnectError("Connection refused")

    with patch("lyrics_gen.ensure_model_loaded", new=AsyncMock(return_value=False)), \
         patch.object(httpx.AsyncClient, "post", new=mock_post):
        result = await lyrics_gen.generate_lyrics("A song description", genre="rock")

    assert result is None


@pytest.mark.asyncio
async def test_short_response_returns_none():
    """When Ollama returns too-short lyrics, generate_lyrics should return None."""
    import lyrics_gen

    async def mock_post(self, url, **kwargs):
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {"response": "Short"}
        resp.raise_for_status = MagicMock()
        return resp

    with patch("lyrics_gen.ensure_model_loaded", new=AsyncMock(return_value=False)), \
         patch.object(httpx.AsyncClient, "post", new=mock_post):
        result = await lyrics_gen.generate_lyrics("A song description", genre="pop")

    assert result is None
