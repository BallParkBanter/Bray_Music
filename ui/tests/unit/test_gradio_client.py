import pytest
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from models import GenerateRequest
import gradio_client


def make_req(**kwargs) -> GenerateRequest:
    defaults = dict(
        title="Test Song",
        description="A rock song",
        lyrics="",
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


def test_builds_correct_param_array():
    req = make_req(description="Epic rock", lyrics="Hello world", duration=2.5, seed="999")
    params, seed = gradio_client._build_params(req)

    assert params[0] == "Epic rock"       # description -> pos 0
    assert params[1] == "Hello world"     # lyrics -> pos 1
    assert params[9] == "999"             # seed -> pos 9 (string)
    assert seed == 999                     # parsed int seed
    assert params[11] == 2.5 * 60         # duration in seconds -> pos 11
    assert params[6] == 8                 # infer_steps -> pos 6 (turbo model = 8 steps)
    assert params[7] == 5.75              # guidance_scale -> pos 7 (creativity=50 -> 10 - 50/100*8.5)
    assert params[27] == "flac"           # format -> pos 27 (API 27, < STATE_INJECTION=37)
    # API 45 (normalization) shifts to real 46 due to hidden State at position 37
    assert params[46] is True             # normalization -> real pos 46 (API 45 + 1)
    assert len(params) == 55


def test_handles_empty_lyrics():
    req = make_req(lyrics="")
    params, _ = gradio_client._build_params(req)
    assert params[1] == ""


def test_handles_random_seed():
    req = make_req(seed="")
    params, seed = gradio_client._build_params(req)
    assert isinstance(seed, int)
    assert 0 <= seed <= 2**31
    assert params[8] is True   # Random Seed = True


def test_handles_explicit_seed():
    req = make_req(seed="42")
    params, seed = gradio_client._build_params(req)
    assert seed == 42
    assert params[9] == "42"
    assert params[8] is False  # Random Seed = False


def test_none_for_unused_params():
    """Unused audio/file params should be None (Gradio default)."""
    req = make_req()
    params, _ = gradio_client._build_params(req)
    # Reference Audio (API 10), Source Audio (API 13), LM Codes Hints (API 14)
    # All < STATE_INJECTION=37, so no shift
    assert params[10] is None  # Reference Audio
    assert params[13] is None  # Source Audio
    assert params[14] is None  # LM Codes Hints
    # API 17 (Instruction) has a non-None default string in the real API
    assert isinstance(params[17], str)
    assert len(params[17]) > 0


def test_bpm_and_key():
    req = make_req(bpm="120", key="C Major")
    params, _ = gradio_client._build_params(req)
    assert params[2] == 120.0  # BPM as float
    assert params[3] == "C Major"


def test_state_injection():
    """Position 37 (hidden State) and 51-54 (States) must be None."""
    req = make_req()
    params, _ = gradio_client._build_params(req)
    assert params[37] is None  # hidden State
    assert params[51] is None  # State
    assert params[52] is None  # State
    assert params[53] is None  # State
    assert params[54] is None  # State


def test_api_to_real_shift():
    """API indices >= 37 should shift +1 in real array."""
    req = make_req()
    params, _ = gradio_client._build_params(req)
    # API 37 (Constrained Decoding Debug = False) -> real 38
    assert params[38] is False
    # API 38 (ParallelThinking = True) -> real 39
    assert params[39] is True
    # API 49 (AutoGen) -> real 50 -- should be False (we use CaptionRewrite, not AutoGen)
    assert params[50] is False


@pytest.mark.asyncio
async def test_parses_sse_stream():
    """Test SSE parsing with realistic Gradio 6.2.0 response format."""
    # Gradio 6.2.0 puts FLAC file objects in data[8] as a list of dicts with 'path' key
    mock_events = [
        "event: generating",
        "data: null",
        "",
        "event: complete",
        'data: [null, null, null, null, null, null, null, null, [{"path": "/tmp/gradio/abc123/test.flac", "url": "/gradio_api/file=/tmp/gradio/abc123/test.flac", "orig_name": "test.flac", "mime_type": "audio/flac"}], null]',
        "",
    ]

    class MockStream:
        async def __aenter__(self): return self
        async def __aexit__(self, *a): pass
        def raise_for_status(self): pass
        async def aiter_lines(self):
            for line in mock_events:
                yield line

    import httpx
    with patch.object(httpx.AsyncClient, 'stream', return_value=MockStream()):
        result = await gradio_client._poll_result(httpx.AsyncClient(), "fake-event-id")
        assert result == "/tmp/gradio/abc123/test.flac"


@pytest.mark.asyncio
async def test_parses_sse_fallback_scan():
    """Test SSE parsing falls back to scanning all items for .flac path."""
    mock_events = [
        "event: complete",
        'data: [{"path": "/tmp/gradio/xyz/song.flac", "url": "http://x/file=song.flac"}]',
        "",
    ]

    class MockStream:
        async def __aenter__(self): return self
        async def __aexit__(self, *a): pass
        def raise_for_status(self): pass
        async def aiter_lines(self):
            for line in mock_events:
                yield line

    import httpx
    with patch.object(httpx.AsyncClient, 'stream', return_value=MockStream()):
        result = await gradio_client._poll_result(httpx.AsyncClient(), "fake-event-id")
        assert result == "/tmp/gradio/xyz/song.flac"


@pytest.mark.asyncio
async def test_error_event_raises():
    """SSE error event should raise RuntimeError."""
    mock_events = [
        "event: error",
        'data: "GPU out of memory"',
    ]

    class MockStream:
        async def __aenter__(self): return self
        async def __aexit__(self, *a): pass
        def raise_for_status(self): pass
        async def aiter_lines(self):
            for line in mock_events:
                yield line

    import httpx
    with patch.object(httpx.AsyncClient, 'stream', return_value=MockStream()):
        with pytest.raises(RuntimeError, match="ACE-Step error"):
            await gradio_client._poll_result(httpx.AsyncClient(), "fake-event-id")


@pytest.mark.asyncio
async def test_generation_error_in_data():
    """Error messages in data array should raise RuntimeError."""
    mock_events = [
        "event: complete",
        'data: ["Error: Generation produced NaN", null]',
        "",
    ]

    class MockStream:
        async def __aenter__(self): return self
        async def __aexit__(self, *a): pass
        def raise_for_status(self): pass
        async def aiter_lines(self):
            for line in mock_events:
                yield line

    import httpx
    with patch.object(httpx.AsyncClient, 'stream', return_value=MockStream()):
        with pytest.raises(RuntimeError, match="ACE-Step generation error"):
            await gradio_client._poll_result(httpx.AsyncClient(), "fake-event-id")


def test_instrumental_mode():
    """When include_vocals=False, lyrics should be [Instrumental]."""
    req = make_req(include_vocals=False, lyrics="Some lyrics that should be ignored")
    params, _ = gradio_client._build_params(req)
    assert params[1] == "[Instrumental]"


def test_vocals_mode_passes_lyrics():
    """When include_vocals=True, lyrics should be passed through."""
    req = make_req(include_vocals=True, lyrics="My real lyrics")
    params, _ = gradio_client._build_params(req)
    assert params[1] == "My real lyrics"


def test_enhance_lyrics_sets_caption_rewrite():
    """When enhance_lyrics=True, CaptionRewrite (API 35) should be True."""
    req = make_req(enhance_lyrics=True)
    params, _ = gradio_client._build_params(req)
    assert params[35] is True  # CaptionRewrite at real pos 35 (API 35 < 37, no shift)


def test_enhance_lyrics_off_by_default():
    """When enhance_lyrics=False, CaptionRewrite should remain False."""
    req = make_req(enhance_lyrics=False, lyrics="Some lyrics here")
    params, _ = gradio_client._build_params(req)
    assert params[35] is False


def test_creativity_maps_to_guidance():
    """Creativity 0-100 maps inversely to guidance scale 10.0-1.5."""
    # creativity=0 (most strict) -> guidance=10.0
    req0 = make_req(creativity=0)
    p0, _ = gradio_client._build_params(req0)
    assert p0[7] == 10.0

    # creativity=100 (most free) -> guidance=1.5
    req100 = make_req(creativity=100)
    p100, _ = gradio_client._build_params(req100)
    assert p100[7] == 1.5

    # creativity=50 -> guidance=5.75
    req50 = make_req(creativity=50)
    p50, _ = gradio_client._build_params(req50)
    assert p50[7] == 5.75


def test_caption_rewrite_not_auto_enabled_for_empty_lyrics():
    """CaptionRewrite (api[35]) should NOT auto-enable for empty lyrics — lyrics gen is handled by Ollama."""
    from gradio_client import _build_params
    from models import GenerateRequest
    req = GenerateRequest(
        title="AI Write My Song",
        description="Upbeat pop about summer",
        lyrics="",
        include_vocals=True,
    )
    params, _ = _build_params(req)
    # CaptionRewrite only activates with explicit enhance_lyrics=True
    assert params[35] is False


def test_caption_rewrite_disabled_when_lyrics_provided():
    """CaptionRewrite should stay False when user wrote their own lyrics."""
    from gradio_client import _build_params
    from models import GenerateRequest
    req = GenerateRequest(
        title="My Lyrics Song",
        description="Rock ballad",
        lyrics="Verse 1: Hello world",
        include_vocals=True,
    )
    params, _ = _build_params(req)
    assert params[35] is False


def test_caption_rewrite_disabled_for_instrumental():
    """CaptionRewrite should stay False for instrumental (no vocals)."""
    from gradio_client import _build_params
    from models import GenerateRequest
    req = GenerateRequest(
        title="Instrumental Track",
        description="Ambient electronic",
        lyrics="",
        include_vocals=False,
    )
    params, _ = _build_params(req)
    assert params[35] is False
