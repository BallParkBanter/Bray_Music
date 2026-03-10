"""Tests for title generation: _initial_title() and lyrics_gen.generate_title()."""

import pytest
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import httpx

sys.path.insert(0, str(Path(__file__).parent.parent.parent))


# ─── _initial_title() ──────────────────────────────────────────────────────


def test_initial_title_with_user_title():
    """User-provided title should be returned with needs_ai_title=False."""
    from main import _initial_title
    from models import GenerateRequest

    req = GenerateRequest(title="My Custom Title", description="A rock song")
    title, needs_ai = _initial_title(req)
    assert title == "My Custom Title"
    assert needs_ai is False


def test_initial_title_strips_whitespace():
    """User title with surrounding whitespace should be stripped."""
    from main import _initial_title
    from models import GenerateRequest

    req = GenerateRequest(title="  Padded Title  ", description="A rock song")
    title, needs_ai = _initial_title(req)
    assert title == "Padded Title"
    assert needs_ai is False


def test_initial_title_empty_uses_description():
    """Empty title should use truncated description with needs_ai_title=True."""
    from main import _initial_title
    from models import GenerateRequest

    req = GenerateRequest(title="", description="A short description")
    title, needs_ai = _initial_title(req)
    assert title == "A short description"
    assert needs_ai is True


def test_initial_title_whitespace_only_uses_description():
    """Whitespace-only title should use truncated description."""
    from main import _initial_title
    from models import GenerateRequest

    req = GenerateRequest(title="   ", description="A short description")
    title, needs_ai = _initial_title(req)
    assert title == "A short description"
    assert needs_ai is True


def test_initial_title_long_description_truncates():
    """Long description should be truncated at 60 chars with ellipsis."""
    from main import _initial_title
    from models import GenerateRequest

    long_desc = "A" * 100
    req = GenerateRequest(title="", description=long_desc)
    title, needs_ai = _initial_title(req)
    assert len(title) == 61  # 60 chars + ellipsis character
    assert title.endswith("\u2026")
    assert needs_ai is True


def test_initial_title_exactly_60_chars_no_ellipsis():
    """Description of exactly 60 chars should not get an ellipsis."""
    from main import _initial_title
    from models import GenerateRequest

    desc = "A" * 60
    req = GenerateRequest(title="", description=desc)
    title, needs_ai = _initial_title(req)
    assert title == desc
    assert "\u2026" not in title
    assert needs_ai is True


# ─── generate_title() ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_generate_title_strips_quotes():
    """generate_title should strip surrounding quotes from the response."""
    import lyrics_gen

    async def mock_post(self, url, **kwargs):
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {"response": '"Midnight Echoes"'}
        resp.raise_for_status = MagicMock()
        return resp

    with patch("lyrics_gen.ensure_model_loaded", new=AsyncMock(return_value=False)), \
         patch.object(httpx.AsyncClient, "post", new=mock_post):
        result = await lyrics_gen.generate_title("A melancholy jazz piece")

    assert result == "Midnight Echoes"


@pytest.mark.asyncio
async def test_generate_title_limits_length():
    """generate_title should truncate titles longer than 60 chars."""
    import lyrics_gen

    long_title = "A" * 100

    async def mock_post(self, url, **kwargs):
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {"response": long_title}
        resp.raise_for_status = MagicMock()
        return resp

    with patch("lyrics_gen.ensure_model_loaded", new=AsyncMock(return_value=False)), \
         patch.object(httpx.AsyncClient, "post", new=mock_post):
        result = await lyrics_gen.generate_title("A very descriptive song")

    assert result is not None
    assert len(result) <= 60


@pytest.mark.asyncio
async def test_generate_title_empty_response_returns_none():
    """generate_title should return None when Ollama returns empty string."""
    import lyrics_gen

    async def mock_post(self, url, **kwargs):
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {"response": ""}
        resp.raise_for_status = MagicMock()
        return resp

    with patch("lyrics_gen.ensure_model_loaded", new=AsyncMock(return_value=False)), \
         patch.object(httpx.AsyncClient, "post", new=mock_post):
        result = await lyrics_gen.generate_title("A song description")

    assert result is None


@pytest.mark.asyncio
async def test_generate_title_none_description_returns_none():
    """generate_title should return None for None description."""
    import lyrics_gen

    result = await lyrics_gen.generate_title(None)
    assert result is None


@pytest.mark.asyncio
async def test_generate_title_empty_description_returns_none():
    """generate_title should return None for empty description."""
    import lyrics_gen

    result = await lyrics_gen.generate_title("")
    assert result is None


@pytest.mark.asyncio
async def test_generate_title_takes_first_line():
    """generate_title should take only the first line of multi-line response."""
    import lyrics_gen

    async def mock_post(self, url, **kwargs):
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {"response": "Good Title\nExtra commentary line"}
        resp.raise_for_status = MagicMock()
        return resp

    with patch("lyrics_gen.ensure_model_loaded", new=AsyncMock(return_value=False)), \
         patch.object(httpx.AsyncClient, "post", new=mock_post):
        result = await lyrics_gen.generate_title("A pop song")

    assert result == "Good Title"


@pytest.mark.asyncio
async def test_generate_title_single_char_returns_none():
    """generate_title should return None for single-character response."""
    import lyrics_gen

    async def mock_post(self, url, **kwargs):
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {"response": "X"}
        resp.raise_for_status = MagicMock()
        return resp

    with patch("lyrics_gen.ensure_model_loaded", new=AsyncMock(return_value=False)), \
         patch.object(httpx.AsyncClient, "post", new=mock_post):
        result = await lyrics_gen.generate_title("A song description")

    assert result is None


@pytest.mark.asyncio
async def test_generate_title_strips_single_quotes():
    """generate_title should strip single quotes from the response."""
    import lyrics_gen

    async def mock_post(self, url, **kwargs):
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {"response": "'Sunset Boulevard'"}
        resp.raise_for_status = MagicMock()
        return resp

    with patch("lyrics_gen.ensure_model_loaded", new=AsyncMock(return_value=False)), \
         patch.object(httpx.AsyncClient, "post", new=mock_post):
        result = await lyrics_gen.generate_title("A cinematic ballad")

    assert result == "Sunset Boulevard"


@pytest.mark.asyncio
async def test_generate_title_handles_exception():
    """generate_title should return None on any exception."""
    import lyrics_gen

    async def mock_post(self, url, **kwargs):
        raise httpx.ConnectError("Connection refused")

    with patch("lyrics_gen.ensure_model_loaded", new=AsyncMock(return_value=False)), \
         patch.object(httpx.AsyncClient, "post", new=mock_post):
        result = await lyrics_gen.generate_title("A song description")

    assert result is None


@pytest.mark.asyncio
async def test_generate_title_strips_think_tags():
    """generate_title should strip <think>...</think> blocks from response."""
    import lyrics_gen

    async def mock_post(self, url, **kwargs):
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {
            "response": "<think>Let me think about this...</think>Neon Skyline"
        }
        resp.raise_for_status = MagicMock()
        return resp

    with patch("lyrics_gen.ensure_model_loaded", new=AsyncMock(return_value=False)), \
         patch.object(httpx.AsyncClient, "post", new=mock_post):
        result = await lyrics_gen.generate_title("A cyberpunk electronic track")

    assert result == "Neon Skyline"
