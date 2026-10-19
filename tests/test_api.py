"""Tests for FITAGE API authentication and connection errors."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.fitage.api import (
    FeelfitApi,
    FeelfitApiError,
    FeelfitAuthError,
    FeelfitConnectionError,
)


def _response_context(status: int, payload: dict[str, object]) -> AsyncMock:
    response = MagicMock()
    response.status = status
    response.json = AsyncMock(return_value=payload)
    context = AsyncMock()
    context.__aenter__.return_value = response
    return context


async def test_get_raises_auth_error_for_expired_token() -> None:
    session = MagicMock()
    session.get.return_value = _response_context(200, {"code": 401})
    api = FeelfitApi(SimpleNamespace(), session, "user@example.test")

    with pytest.raises(FeelfitAuthError):
        await api._get("/test")


async def test_get_does_not_classify_forbidden_response_as_expired_token() -> None:
    session = MagicMock()
    session.get.return_value = _response_context(403, {"code": 403})
    api = FeelfitApi(SimpleNamespace(), session, "user@example.test")

    with pytest.raises(FeelfitApiError) as error:
        await api._get("/test")

    assert not isinstance(error.value, FeelfitAuthError)


async def test_get_respects_api_code_over_http_401() -> None:
    session = MagicMock()
    session.get.return_value = _response_context(401, {"code": 403})
    api = FeelfitApi(SimpleNamespace(), session, "user@example.test")

    with pytest.raises(FeelfitApiError) as error:
        await api._get("/test")

    assert not isinstance(error.value, FeelfitAuthError)


async def test_get_does_not_classify_api_forbidden_code_as_expired_token() -> None:
    session = MagicMock()
    session.get.return_value = _response_context(200, {"code": 403})
    api = FeelfitApi(SimpleNamespace(), session, "user@example.test")

    with pytest.raises(FeelfitApiError) as error:
        await api._get("/test")

    assert not isinstance(error.value, FeelfitAuthError)


async def test_login_rejects_explicit_auth_error_code() -> None:
    hass = SimpleNamespace(async_add_executor_job=AsyncMock(return_value="encrypted"))
    session = MagicMock()
    session.post.return_value = _response_context(200, {"code": 401})
    api = FeelfitApi(hass, session, "user@example.test")

    with pytest.raises(FeelfitAuthError):
        await api.async_login("password")


async def test_login_does_not_classify_forbidden_code_as_invalid_credentials() -> None:
    hass = SimpleNamespace(async_add_executor_job=AsyncMock(return_value="encrypted"))
    session = MagicMock()
    session.post.return_value = _response_context(200, {"code": 403})
    api = FeelfitApi(hass, session, "user@example.test")

    with pytest.raises(FeelfitApiError) as error:
        await api.async_login("password")

    assert not isinstance(error.value, FeelfitAuthError)


async def test_login_does_not_expose_error_response_body(
    caplog: pytest.LogCaptureFixture,
) -> None:
    hass = SimpleNamespace(async_add_executor_job=AsyncMock(return_value="encrypted"))
    session = MagicMock()
    session.post.return_value = _response_context(
        500, {"code": 500, "token": "secret-token", "password": "secret-password"}
    )
    api = FeelfitApi(hass, session, "user@example.test")

    with pytest.raises(FeelfitApiError) as error:
        await api.async_login("secret-password")

    assert "secret-token" not in str(error.value)
    assert "secret-password" not in str(error.value)
    assert "secret-token" not in caplog.text
    assert "secret-password" not in caplog.text


async def test_login_keeps_other_api_errors_out_of_reauth() -> None:
    hass = SimpleNamespace(async_add_executor_job=AsyncMock(return_value="encrypted"))
    session = MagicMock()
    session.post.return_value = _response_context(200, {"code": 500})
    api = FeelfitApi(hass, session, "user@example.test")

    with pytest.raises(FeelfitApiError) as error:
        await api.async_login("password")

    assert not isinstance(error.value, FeelfitAuthError)


async def test_get_distinguishes_temporary_connection_failure() -> None:
    session = MagicMock()
    session.get.side_effect = TimeoutError
    api = FeelfitApi(SimpleNamespace(), session, "user@example.test")

    with pytest.raises(FeelfitConnectionError):
        await api._get("/test")


async def test_get_does_not_classify_server_failure_as_auth_error() -> None:
    session = MagicMock()
    session.get.return_value = _response_context(503, {})
    api = FeelfitApi(SimpleNamespace(), session, "user@example.test")

    with pytest.raises(FeelfitApiError) as error:
        await api._get("/test")

    assert not isinstance(error.value, FeelfitAuthError)
