from __future__ import annotations

import aiohttp
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer
import pytest

from custom_components.inferencia_presencia.panel_proxy import (
    InferenciaPresenciaPanelProxyView,
    build_proxy_target,
    panel_uses_proxy,
    proxy_panel_url,
    validate_proxy_path,
)


def runtime_for(url: str, session=None, panel_url: str = "") -> dict:
    return {
        "backend_url": url,
        "panel_base_url": panel_url,
        "http_session": session,
    }


def test_panel_url_selection_and_query_preservation() -> None:
    assert panel_uses_proxy("") is True
    assert panel_uses_proxy("http://backend.local:8081") is True
    assert panel_uses_proxy("https://panel.example.test") is False
    url = proxy_panel_url(
        "token",
        "http://backend.local:8081/?custom=1",
        True,
    )
    assert url.startswith("/api/inferencia_presencia/panel/token/")
    assert "custom=1" in url
    assert "embedded=1" in url
    assert "dev=1" in url


def test_proxy_target_is_bound_to_configured_backend() -> None:
    target = build_proxy_target(
        runtime_for("http://backend.local:8081/base"),
        "api/sim_data",
        {"page": "2"},
    )
    assert str(target) == "http://backend.local:8081/base/api/sim_data?page=2"
    panel_target = build_proxy_target(
        runtime_for(
            "http://backend.local:8081",
            panel_url="http://browser-only.test/custom-panel?theme=dark",
        ),
        "",
        {"theme": "dark"},
    )
    assert str(panel_target) == (
        "http://backend.local:8081/custom-panel?theme=dark"
    )
    with pytest.raises(web.HTTPBadRequest):
        validate_proxy_path("../admin")
    with pytest.raises(web.HTTPBadRequest):
        validate_proxy_path("%2e%2e/admin")
    with pytest.raises(web.HTTPBadRequest):
        validate_proxy_path(r"api\admin")


@pytest.mark.asyncio
async def test_proxy_forwards_http_and_rewrites_swagger_path() -> None:
    async def index(_request):
        return web.Response(
            text='url: "/openapi.json"',
            content_type="text/html",
        )

    async def echo(request):
        return web.json_response(
            {
                "method": request.method,
                "value": (await request.json()).get("value"),
                "query": request.query.get("query"),
                "authorization": request.headers.get("Authorization"),
            }
        )

    backend_app = web.Application()
    backend_app.router.add_get("/", index)
    backend_app.router.add_post("/api/echo", echo)
    backend_server = TestServer(backend_app)
    await backend_server.start_server()
    session = aiohttp.ClientSession()
    runtime = runtime_for(str(backend_server.make_url("/")), session)
    view = InferenciaPresenciaPanelProxyView(
        {"panel_tokens": {"valid": runtime}}
    )
    proxy_app = web.Application()

    async def proxy_handler(request):
        return await view._handle(
            request,
            request.match_info["token"],
            request.match_info["path"],
        )

    proxy_app.router.add_route(
        "*",
        "/api/inferencia_presencia/panel/{token}/{path:.*}",
        proxy_handler,
    )
    proxy_client = TestClient(TestServer(proxy_app))
    await proxy_client.start_server()
    try:
        root = await proxy_client.get(
            "/api/inferencia_presencia/panel/valid/"
        )
        assert root.status == 200
        assert 'url: "openapi.json"' in await root.text()
        assert root.headers["Cache-Control"] == "no-store"

        echoed = await proxy_client.post(
            "/api/inferencia_presencia/panel/valid/api/echo?query=ok",
            json={"value": 7},
            headers={"Authorization": "Bearer private"},
        )
        assert echoed.status == 200
        assert await echoed.json() == {
            "method": "POST",
            "value": 7,
            "query": "ok",
            "authorization": None,
        }
        missing = await proxy_client.get(
            "/api/inferencia_presencia/panel/invalid/"
        )
        assert missing.status == 404
    finally:
        await proxy_client.close()
        await session.close()
        await backend_server.close()


@pytest.mark.asyncio
async def test_proxy_forwards_websocket_messages() -> None:
    async def websocket_echo(request):
        socket = web.WebSocketResponse()
        await socket.prepare(request)
        async for message in socket:
            if message.type is aiohttp.WSMsgType.TEXT:
                await socket.send_str("eco:" + message.data)
        return socket

    backend_app = web.Application()
    backend_app.router.add_get("/presencia", websocket_echo)
    backend_server = TestServer(backend_app)
    await backend_server.start_server()
    session = aiohttp.ClientSession()
    runtime = runtime_for(str(backend_server.make_url("/")), session)
    view = InferenciaPresenciaPanelProxyView(
        {"panel_tokens": {"valid": runtime}}
    )
    proxy_app = web.Application()

    async def proxy_handler(request):
        return await view._handle(
            request,
            request.match_info["token"],
            request.match_info["path"],
        )

    proxy_app.router.add_route(
        "*",
        "/api/inferencia_presencia/panel/{token}/{path:.*}",
        proxy_handler,
    )
    proxy_client = TestClient(TestServer(proxy_app))
    await proxy_client.start_server()
    try:
        socket = await proxy_client.ws_connect(
            "/api/inferencia_presencia/panel/valid/presencia"
        )
        await socket.send_str("hola")
        message = await socket.receive(timeout=2)
        assert message.data == "eco:hola"
        await socket.close()
    finally:
        await proxy_client.close()
        await session.close()
        await backend_server.close()
