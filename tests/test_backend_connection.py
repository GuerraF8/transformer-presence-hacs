from __future__ import annotations

import aiohttp
import pytest

from custom_components.inferencia_presencia.backend_client import (
    BackendConnectionError,
    validate_backend_connection,
)


class FakeResponse:
    def __init__(self, status: int, body: str) -> None:
        self.status = status
        self._body = body

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args) -> None:
        return None

    async def text(self) -> str:
        return self._body


class FakeSession:
    def __init__(
        self,
        response: FakeResponse | None = None,
        error: Exception | None = None,
    ) -> None:
        self.response = response
        self.error = error
        self.requested_url = ""

    def get(self, url: str, **_kwargs):
        self.requested_url = url
        if self.error is not None:
            raise self.error
        return self.response


@pytest.mark.asyncio
async def test_backend_connection_accepts_healthy_backend() -> None:
    session = FakeSession(FakeResponse(200, '{"status":"ok"}'))

    await validate_backend_connection(session, "http://192.168.0.221:8081/")

    assert session.requested_url == "http://192.168.0.221:8081/api/health"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("response", "error"),
    [
        (FakeResponse(503, '{"detail":"unavailable"}'), None),
        (FakeResponse(200, '{"status":"starting"}'), None),
        (FakeResponse(200, "no-json"), None),
        (None, aiohttp.ClientConnectionError("sin ruta")),
    ],
)
async def test_backend_connection_rejects_unreachable_or_invalid_backend(
    response: FakeResponse | None,
    error: Exception | None,
) -> None:
    with pytest.raises(BackendConnectionError):
        await validate_backend_connection(
            FakeSession(response, error),
            "http://127.0.0.1:8081",
        )
