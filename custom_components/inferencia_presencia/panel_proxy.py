"""Proxy del panel entre Home Assistant y el backend de inferencia."""

from __future__ import annotations

import asyncio
from collections.abc import Iterable, Mapping
import logging
from urllib.parse import parse_qsl, urlencode, unquote, urlparse

import aiohttp
from aiohttp import ClientWebSocketResponse, hdrs, web
from multidict import CIMultiDict
from yarl import URL

from homeassistant.components.http import HomeAssistantView

from .runtime import IntegrationRuntime

LOGGER = logging.getLogger(__name__)

PANEL_PROXY_PREFIX = "/api/inferencia_presencia/panel"
REQUEST_HEADERS_BLOCKED = {
    "authorization",
    "connection",
    "content-length",
    "cookie",
    "host",
    "proxy-authenticate",
    "proxy-authorization",
    "sec-websocket-extensions",
    "sec-websocket-key",
    "sec-websocket-protocol",
    "sec-websocket-version",
    "te",
    "trailer",
    "transfer-encoding",
    "upgrade",
}
RESPONSE_HEADERS_BLOCKED = {
    "connection",
    "content-encoding",
    "content-length",
    "set-cookie",
    "transfer-encoding",
}


def panel_uses_proxy(panel_url: str) -> bool:
    """Determina si el panel debe publicarse mediante el origen de Home Assistant."""

    return urlparse(panel_url).scheme.lower() != "https"


def proxy_panel_url(
    token: str,
    source_url: str,
    dev_mode: bool,
) -> str:
    """Construye la URL relativa que Home Assistant cargará en el iframe."""

    query = dict(parse_qsl(urlparse(source_url).query, keep_blank_values=True))
    query["embedded"] = "1"
    query["dev"] = "1" if dev_mode else "0"
    suffix = f"?{urlencode(query)}" if query else ""
    return f"{PANEL_PROXY_PREFIX}/{token}/{suffix}"


def validate_proxy_path(path: str) -> str:
    """Valida y normaliza una ruta relativa antes de enviarla al backend."""

    decoded = unquote(path or "")
    if "\x00" in decoded or "\\" in decoded:
        raise web.HTTPBadRequest(text="ruta de panel no válida")
    parts = [part for part in decoded.split("/") if part]
    if any(part in {".", ".."} for part in parts):
        raise web.HTTPBadRequest(text="ruta de panel no válida")
    return "/".join(parts)


def build_proxy_target(
    runtime: IntegrationRuntime,
    path: str,
    query: Mapping[str, str] | None = None,
) -> URL:
    """Resuelve una ruta validada contra el backend configurado."""

    safe_path = validate_proxy_path(path)
    if not safe_path:
        target = URL(runtime["backend_url"])
        panel_source = runtime.get("panel_base_url")
        if panel_source:
            source_path = URL(panel_source).path
            if source_path not in {"", "/"}:
                target = target.with_path(source_path)
    else:
        base = URL(runtime["backend_url"].rstrip("/") + "/")
        target = base.join(URL(safe_path))
    if target.scheme not in {"http", "https"} or not target.host:
        raise web.HTTPBadGateway(text="URL del backend no válida")
    if query:
        target = target.update_query(query)
    return target


def _request_headers(request: web.Request) -> CIMultiDict[str]:
    return CIMultiDict(
        (name, value)
        for name, value in request.headers.items()
        if name.lower() not in REQUEST_HEADERS_BLOCKED
    )


def _response_headers(response: aiohttp.ClientResponse) -> CIMultiDict[str]:
    headers = CIMultiDict(
        (name, value)
        for name, value in response.headers.items()
        if name.lower() not in RESPONSE_HEADERS_BLOCKED
        and name.lower() != "location"
    )
    headers["Cache-Control"] = "no-store"
    headers["Referrer-Policy"] = "no-referrer"
    return headers


def _is_websocket(request: web.Request) -> bool:
    return (
        "upgrade" in request.headers.get(hdrs.CONNECTION, "").lower()
        and request.headers.get(hdrs.UPGRADE, "").lower() == "websocket"
    )


def _rewrite_html(body: bytes) -> bytes:
    """Adapta las referencias raíz generadas por Swagger al prefijo del proxy."""

    text = body.decode("utf-8")
    text = text.replace('url: "/openapi.json"', 'url: "openapi.json"')
    text = text.replace("url: '/openapi.json'", "url: 'openapi.json'")
    return text.encode("utf-8")


async def _forward_websocket(
    source: web.WebSocketResponse | ClientWebSocketResponse,
    target: web.WebSocketResponse | ClientWebSocketResponse,
) -> None:
    try:
        async for message in source:
            if message.type is aiohttp.WSMsgType.TEXT:
                await target.send_str(message.data)
            elif message.type is aiohttp.WSMsgType.BINARY:
                await target.send_bytes(message.data)
            elif message.type is aiohttp.WSMsgType.PING:
                await target.ping(message.data)
            elif message.type is aiohttp.WSMsgType.PONG:
                await target.pong(message.data)
            elif message.type in {
                aiohttp.WSMsgType.CLOSE,
                aiohttp.WSMsgType.CLOSED,
                aiohttp.WSMsgType.ERROR,
            }:
                break
    except (ConnectionError, RuntimeError):
        return
    finally:
        if not target.closed:
            await target.close()


class InferenciaPresenciaPanelProxyView(HomeAssistantView):
    """Publica el backend en el mismo origen que Home Assistant."""

    url = f"{PANEL_PROXY_PREFIX}/{{token}}/{{path:.*}}"
    name = "api:inferencia_presencia:panel_proxy"
    requires_auth = False

    def __init__(self, domain_data: dict) -> None:
        self._domain_data = domain_data

    def _runtime(self, token: str) -> IntegrationRuntime:
        runtime = self._domain_data.get("panel_tokens", {}).get(token)
        if runtime is None:
            raise web.HTTPNotFound(text="panel no disponible")
        return runtime

    async def _handle(
        self,
        request: web.Request,
        token: str,
        path: str,
    ) -> web.StreamResponse:
        runtime = self._runtime(token)
        if _is_websocket(request):
            return await self._handle_websocket(request, runtime, path)
        return await self._handle_http(request, runtime, token, path)

    get = _handle
    post = _handle
    put = _handle
    patch = _handle
    delete = _handle
    head = _handle
    options = _handle

    async def _handle_http(
        self,
        request: web.Request,
        runtime: IntegrationRuntime,
        token: str,
        path: str,
    ) -> web.Response:
        target = build_proxy_target(runtime, path, request.query)
        try:
            async with runtime["http_session"].request(
                request.method,
                target,
                headers=_request_headers(request),
                data=request.content if request.can_read_body else None,
                allow_redirects=False,
                timeout=aiohttp.ClientTimeout(total=None),
            ) as upstream:
                body = await upstream.read()
                content_type = upstream.headers.get(
                    hdrs.CONTENT_TYPE,
                    "application/octet-stream",
                )
                if content_type.startswith("text/html"):
                    body = _rewrite_html(body)
                headers = _response_headers(upstream)
                location = upstream.headers.get(hdrs.LOCATION)
                if location:
                    rewritten = self._rewrite_location(runtime, token, location)
                    if rewritten:
                        headers[hdrs.LOCATION] = rewritten
                return web.Response(
                    body=body,
                    status=upstream.status,
                    headers=headers,
                )
        except (aiohttp.ClientError, TimeoutError) as err:
            LOGGER.warning("No se pudo acceder al panel de inferencia: %s", err)
            raise web.HTTPBadGateway(text="backend de inferencia no disponible") from err

    @staticmethod
    def _rewrite_location(
        runtime: IntegrationRuntime,
        token: str,
        location: str,
    ) -> str | None:
        target = URL(location)
        backend = URL(runtime["backend_url"])
        if target.is_absolute() and target.origin() != backend.origin():
            return None
        path = target.path.lstrip("/")
        suffix = f"?{target.query_string}" if target.query_string else ""
        return f"{PANEL_PROXY_PREFIX}/{token}/{path}{suffix}"

    async def _handle_websocket(
        self,
        request: web.Request,
        runtime: IntegrationRuntime,
        path: str,
    ) -> web.WebSocketResponse:
        protocols: Iterable[str] = tuple(
            item.strip()
            for item in request.headers.get(hdrs.SEC_WEBSOCKET_PROTOCOL, "").split(",")
            if item.strip()
        )
        server = web.WebSocketResponse(
            protocols=protocols,
            autoclose=False,
            autoping=False,
        )
        await server.prepare(request)
        target = build_proxy_target(runtime, path, request.query)
        try:
            async with runtime["http_session"].ws_connect(
                target,
                headers=_request_headers(request),
                protocols=protocols,
                autoclose=False,
                autoping=False,
                timeout=aiohttp.ClientWSTimeout(ws_close=None),
            ) as client:
                tasks = {
                    asyncio.create_task(_forward_websocket(server, client)),
                    asyncio.create_task(_forward_websocket(client, server)),
                }
                done, pending = await asyncio.wait(
                    tasks,
                    return_when=asyncio.FIRST_COMPLETED,
                )
                for task in pending:
                    task.cancel()
                await asyncio.gather(*done, *pending, return_exceptions=True)
        except (aiohttp.ClientError, TimeoutError) as err:
            LOGGER.warning("WebSocket del panel no disponible: %s", err)
            await server.close(code=1011, message=b"backend no disponible")
        return server
