"""Vistas HTTP autenticadas publicadas por la integración."""

from __future__ import annotations

import logging
from typing import Any

from aiohttp import web

from homeassistant.components.http import HomeAssistantView
from homeassistant.core import HomeAssistant

from .catalog import refresh_catalog_for_all
from .const import DOMAIN
from .ha_utils import coerce_bool
from .test_sensors import create_test_sensors_for_all

LOGGER = logging.getLogger(__name__)


class InferenciaPresenciaStatusView(HomeAssistantView):
    url = "/api/inferencia_presencia/status"
    name = "api:inferencia_presencia:status"
    requires_auth = True

    def __init__(self, domain_data: dict[str, Any]) -> None:
        self._domain_data = domain_data

    async def get(self, request) -> web.Response:
        entries = []
        for entry_id, runtime in self._domain_data["entries"].items():
            coordinator = runtime.get("coordinator")
            entries.append(
                {
                    "entry_id": entry_id,
                    "backend_url": runtime["backend_url"],
                    "panel_base_url": runtime.get("panel_base_url", ""),
                    "tracked_entities": sorted(runtime["tracked_entities"]),
                    "auto_discovery": runtime["auto_discovery"],
                    "last_event": runtime["last_event"],
                    "last_backend_response": runtime["last_backend_response"],
                    "last_error": runtime["last_error"],
                    "last_push_at": runtime["last_push_at"],
                    "last_scan_at": runtime["last_scan_at"],
                    "available_entities_total": runtime["available_entities_total"],
                    "supported_entities_total": runtime["supported_entities_total"],
                    "available_entities": runtime["available_entities"],
                    "recent_events": list(runtime["recent_events"]),
                    "sent_events": runtime["sent_events"],
                    "failed_events": runtime["failed_events"],
                    "enabled_real_entities": sorted(
                        runtime.get("enabled_real_entities", set())
                    ),
                    "last_real_sensor_sync_at": runtime.get(
                        "last_real_sensor_sync_at"
                    ),
                    "presence_update_success": bool(
                        coordinator and coordinator.last_update_success
                    ),
                    "presence_update_failures": getattr(
                        coordinator, "consecutive_failures", 0
                    ),
                }
            )
        return web.json_response(
            {
                "domain": DOMAIN,
                "panel_url": self._domain_data.get("panel_url"),
                "entries": entries,
            }
        )


class InferenciaPresenciaActionsView(HomeAssistantView):
    url = "/api/inferencia_presencia/actions"
    name = "api:inferencia_presencia:actions"
    requires_auth = True

    def __init__(self, hass: HomeAssistant, domain_data: dict[str, Any]) -> None:
        self._hass = hass
        self._domain_data = domain_data

    async def post(self, request) -> web.Response:
        if not self._domain_data["entries"]:
            return web.json_response(
                {"status": "error", "error": "no hay entradas activas"},
                status=409,
            )
        try:
            payload = await request.json()
        except Exception:
            payload = {}
        action = str(payload.get("action", "")).strip()
        if action == "refresh_catalog":
            results = await refresh_catalog_for_all(self._hass, self._domain_data)
            return web.json_response(
                {"status": "ok", "action": action, "entries": results}
            )
        if action == "create_test_sensors":
            results = await create_test_sensors_for_all(
                self._hass,
                self._domain_data,
                rooms_raw=str(payload.get("rooms", "bedroom,kitchen,living")),
                include_occupancy=coerce_bool(
                    payload.get("include_occupancy"), True
                ),
                initial_state=str(payload.get("initial_state", "off")),
            )
            return web.json_response(
                {"status": "ok", "action": action, "entries": results}
            )
        return web.json_response(
            {"status": "error", "error": f"accion no soportada: {action}"},
            status=400,
        )


def register_status_views(
    hass: HomeAssistant, domain_data: dict[str, Any]
) -> None:
    if domain_data.get("status_view_registered"):
        return
    if not hasattr(hass, "http"):
        LOGGER.warning(
            "No se pudo registrar vista de estado de %s: HTTP no disponible",
            DOMAIN,
        )
        return
    try:
        hass.http.register_view(InferenciaPresenciaStatusView(domain_data))
        hass.http.register_view(InferenciaPresenciaActionsView(hass, domain_data))
    except Exception as err:  # noqa: BLE001
        LOGGER.error("No se pudo registrar vista de estado de %s: %s", DOMAIN, err)
        return
    domain_data["status_view_registered"] = True
