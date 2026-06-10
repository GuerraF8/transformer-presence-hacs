from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

import aiohttp

from .ha_utils import build_url
from .runtime import IntegrationRuntime

LOGGER = logging.getLogger(__name__)


async def post_json(
    runtime: IntegrationRuntime,
    path: str,
    payload: dict[str, Any],
    timeout_seconds: float = 60,
) -> dict[str, Any] | None:
    endpoint = build_url(runtime["backend_url"], path)
    timeout = aiohttp.ClientTimeout(total=timeout_seconds)
    async with runtime["http_session"].post(
        endpoint, json=payload, timeout=timeout
    ) as response:
        body = await response.text()
        if response.status >= 400:
            raise RuntimeError(f"Backend retorno {response.status} para {path}: {body}")
        if not body:
            return None
        try:
            parsed = await response.json()
        except ValueError:
            return {"raw": body}
        return parsed if isinstance(parsed, dict) else {"raw": parsed}


async def get_json(
    runtime: IntegrationRuntime,
    path: str,
    timeout_seconds: float = 8,
) -> dict[str, Any] | None:
    endpoint = build_url(runtime["backend_url"], path)
    timeout = aiohttp.ClientTimeout(total=timeout_seconds)
    async with runtime["http_session"].get(endpoint, timeout=timeout) as response:
        body = await response.text()
        if response.status >= 400:
            raise RuntimeError(f"Backend retorno {response.status} para {path}: {body}")
        if not body:
            return None
        try:
            parsed = await response.json()
        except ValueError:
            return {"raw": body}
        return parsed if isinstance(parsed, dict) else {"raw": parsed}


async def forward_event(
    runtime: IntegrationRuntime,
    payload: dict[str, Any],
) -> None:
    endpoint = build_url(runtime["backend_url"], "/api/events")
    timeout = aiohttp.ClientTimeout(total=10)
    try:
        async with runtime["http_session"].post(
            endpoint, json=payload, timeout=timeout
        ) as response:
            body = await response.text()
            if response.status >= 400:
                runtime["failed_events"] += 1
                runtime["last_error"] = (
                    f"Backend retorno {response.status} para "
                    f"{payload['entity_id']}: {body}"
                )
                runtime["recent_events"].append(
                    {
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "ok": False,
                        "entity_id": payload["entity_id"],
                        "state": payload["state"],
                        "error": runtime["last_error"],
                    }
                )
                LOGGER.error(runtime["last_error"])
                return
            parsed: dict[str, Any] | None = None
            if body:
                try:
                    maybe_json = await response.json()
                    parsed = maybe_json if isinstance(maybe_json, dict) else {"raw": maybe_json}
                except ValueError:
                    parsed = {"raw": body}
            runtime["sent_events"] += 1
            runtime["last_error"] = None
            runtime["last_event"] = payload
            runtime["last_backend_response"] = parsed
            runtime["last_push_at"] = datetime.now(timezone.utc).isoformat()
            runtime["recent_events"].append(
                {
                    "timestamp": runtime["last_push_at"],
                    "ok": True,
                    "entity_id": payload["entity_id"],
                    "state": payload["state"],
                    "sensor_type": payload["sensor_type"],
                    "room": payload["room"],
                }
            )
            coordinator = runtime.get("coordinator")
            if coordinator is not None:
                coordinator.async_apply_event_response(parsed)
    except (aiohttp.ClientError, TimeoutError) as err:
        runtime["failed_events"] += 1
        runtime["last_error"] = f"No fue posible enviar evento a {endpoint}: {err}"
        runtime["recent_events"].append(
            {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "ok": False,
                "entity_id": payload["entity_id"],
                "state": payload["state"],
                "error": runtime["last_error"],
            }
        )
        LOGGER.error(runtime["last_error"])
