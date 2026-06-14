"""Acciones de Home Assistant solicitadas por el backend y su consulta periódica."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlencode

from homeassistant.core import HomeAssistant

from .backend_client import get_json, post_json
from .catalog import refresh_catalog_for_all, sync_real_sensor_selection
from .ha_utils import coerce_bool
from .runtime import IntegrationRuntime
from .test_sensors import (
    create_test_sensors_for_all,
    remove_test_resources_for_all,
)

LOGGER = logging.getLogger(__name__)


async def execute_backend_action(
    hass: HomeAssistant,
    domain_data: dict[str, Any],
    action_request: dict[str, Any],
) -> dict[str, Any]:
    action = str(action_request.get("action", "")).strip()
    payload = (
        action_request.get("payload")
        if isinstance(action_request.get("payload"), dict)
        else {}
    )
    if action == "refresh_catalog":
        entries = await refresh_catalog_for_all(hass, domain_data)
        return {"status": "ok", "action": action, "entries": entries}
    if action == "create_test_sensors":
        report = await create_test_sensors_for_all(
            hass,
            domain_data,
            rooms_raw=str(payload.get("rooms", "bedroom,kitchen,living")),
            include_occupancy=coerce_bool(payload.get("include_occupancy"), True),
            initial_state=str(payload.get("initial_state", "off")),
        )
        return {"status": "ok", "action": action, **report}
    if action in {"remove_test_sensors", "remove_test_resources"}:
        result = await remove_test_resources_for_all(
            hass,
            domain_data,
            include_areas=action == "remove_test_resources",
        )
        return {"action": action, **result}
    return {"status": "error", "action": action, "error": "accion no soportada"}


async def publish_integration_status(
    runtime: IntegrationRuntime, *, poller_state: str
) -> None:
    payload = {
        "entry_id": runtime["entry_id"],
        "backend_url": runtime["backend_url"],
        "poller_state": poller_state,
        "last_error": runtime["last_error"],
        "last_scan_at": runtime["last_scan_at"],
        "available_entities_total": runtime["available_entities_total"],
        "supported_entities_total": runtime["supported_entities_total"],
        "auto_discovery": runtime["auto_discovery"],
        "tracked_entities": sorted(runtime["tracked_entities"]),
        "enabled_real_entities": sorted(runtime.get("enabled_real_entities", set())),
        "last_real_sensor_sync_at": runtime.get("last_real_sensor_sync_at"),
    }
    await post_json(
        runtime, "/api/ha_integration_status", payload, timeout_seconds=8
    )


async def poll_backend_actions(
    hass: HomeAssistant,
    domain_data: dict[str, Any],
    runtime: IntegrationRuntime,
) -> None:
    while True:
        await asyncio.sleep(2)
        request_id = ""
        try:
            await sync_real_sensor_selection(runtime)
            await publish_integration_status(runtime, poller_state="polling")
            query = urlencode({"entry_id": runtime["entry_id"]})
            action_request = await get_json(
                runtime, f"/api/ha_actions/pending?{query}"
            )
            if not action_request or action_request.get("status") == "empty":
                continue
            request_id = str(action_request.get("request_id", ""))
            result = await execute_backend_action(hass, domain_data, action_request)
            if request_id:
                await post_json(
                    runtime,
                    f"/api/ha_actions/{request_id}/result",
                    result,
                    timeout_seconds=8,
                )
            runtime["recent_events"].append(
                {
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "ok": result.get("status") == "ok",
                    "entity_id": f"ui.{action_request.get('action', 'ha_action')}",
                    "state": str(result.get("status", "unknown")),
                    "sensor_type": "service",
                    "room": "home_assistant",
                }
            )
            await publish_integration_status(runtime, poller_state="executed_action")
        except asyncio.CancelledError:
            raise
        except Exception as err:  # noqa: BLE001
            runtime["last_error"] = (
                f"No fue posible ejecutar accion solicitada desde UI: {err!r}"
            )
            LOGGER.error(runtime["last_error"])
            if request_id:
                try:
                    await post_json(
                        runtime,
                        f"/api/ha_actions/{request_id}/result",
                        {"status": "error", "error": str(err)},
                        timeout_seconds=8,
                    )
                except Exception:  # noqa: BLE001
                    LOGGER.debug(
                        "No se pudo reportar error de accion HA al backend",
                        exc_info=True,
                    )
