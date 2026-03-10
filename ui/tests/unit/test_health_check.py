"""Tests for gradio_client.check_health()."""

import pytest
from unittest.mock import AsyncMock, patch
import httpx

from gradio_client import check_health


@pytest.mark.asyncio
async def test_health_check_returns_true_when_reachable():
    """Health check returns True when ACE-Step responds 200."""
    mock_response = AsyncMock()
    mock_response.status_code = 200

    with patch("gradio_client.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        result = await check_health()
        assert result is True


@pytest.mark.asyncio
async def test_health_check_returns_false_on_connection_error():
    """Health check returns False when ACE-Step is unreachable."""
    with patch("gradio_client.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.get.side_effect = httpx.ConnectError("Connection refused")
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        result = await check_health()
        assert result is False


@pytest.mark.asyncio
async def test_health_check_returns_false_on_timeout():
    """Health check returns False when ACE-Step times out."""
    with patch("gradio_client.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.get.side_effect = httpx.TimeoutException("Timeout")
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        result = await check_health()
        assert result is False


@pytest.mark.asyncio
async def test_health_check_returns_false_on_500():
    """Health check returns False when ACE-Step responds with error."""
    mock_response = AsyncMock()
    mock_response.status_code = 500

    with patch("gradio_client.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        result = await check_health()
        assert result is False
