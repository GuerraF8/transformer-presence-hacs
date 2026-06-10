"""Esquemas y registro de servicios de Home Assistant."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

import voluptuous as vol

from homeassistant.core import HomeAssistant, ServiceCall

from .backend_client import forward_event, post_json
from .catalog import refresh_catalog_for_all
from .const import (
    DOMAIN,
    SERVICE_CREATE_TEST_SENSORS,
    SERVICE_EMIT_TEST_EVENT,
    SERVICE_REFRESH_SENSOR_CATALOG,
    SERVICE_START_FULL_REPLAY,
)
from .ha_utils import coerce_bool
from .test_sensors import create_test_sensors_for_all

LOGGER = logging.getLogger(__name__)

TEST_EVENT_SCHEMA = vol.Schema(
    {
        vol.Required("room"): str,
        vol.Optional("sensor_type", default="motion"): str,
        vol.Optional("state", default="on"): str,
        vol.Optional("entity_id"): str,
        vol.Optional("timestamp"): str,
    }
)
FULL_REPLAY_SCHEMA = vol.Schema(
    {
        vol.Optional("csv_path", default="/data/history-1mes_sorted.csv"): str,
        vol.Optional("speed_events_per_second", default=30): vol.All(
            vol.Coerce(float), vol.Range(min=1, max=200)
        ),
        vol.Optional("debounce_seconds", default=1): vol.All(
            vol.Coerce(int), vol.Range(min=0, max=120)
        ),
        vol.Optional("include_all_state_transitions", default=True): bool,
        vol.Optional("max_events", default=0): vol.All(
            vol.Coerce(int), vol.Range(min=0, max=1_000_000)
        ),
    }
)
REFRESH_CATALOG_SCHEMA = vol.Schema({})
CREATE_TEST_SENSORS_SCHEMA = vol.Schema(
    {
        vol.Optional("rooms", default="bedroom,kitchen,living"): str,
        vol.Optional("include_occupancy", default=True): bool,
        vol.Optional("initial_state", default="off"): str,
    }
)


async def ensure_services(
    hass: HomeAssistant, domain_data: dict[str, Any]
) -> None:
    if domain_data.get("services_registered"):
        return
    service_names = [
        SERVICE_EMIT_TEST_EVENT,
        SERVICE_START_FULL_REPLAY,
        SERVICE_REFRESH_SENSOR_CATALOG,
        SERVICE_CREATE_TEST_SENSORS,
    ]
    if all(hass.services.has_service(DOMAIN, name) for name in service_names):
        domain_data["services_registered"] = True
        return
    for name in service_names:
        if hass.services.has_service(DOMAIN, name):
            hass.services.async_remove(DOMAIN, name)

    async def emit_test_event(call: ServiceCall) -> None:
        if not domain_data["entries"]:
            LOGGER.warning("No hay entradas activas de %s", DOMAIN)
            return
        runtime = next(iter(domain_data["entries"].values()))
        room = str(call.data["room"]).strip().lower()
        sensor_type = str(call.data.get("sensor_type", "motion")).strip().lower()
        entity_id = str(call.data.get("entity_id", "")).strip().lower()
        payload: dict[str, Any] = {
            "entity_id": entity_id or f"simulated_sensor.{room}_{sensor_type}",
            "state": str(call.data.get("state", "on")).strip().lower(),
            "sensor_type": sensor_type,
            "room": room,
            "source": "ha_test_service",
        }
        timestamp = str(call.data.get("timestamp", "")).strip()
        if timestamp:
            payload["timestamp"] = timestamp
        await forward_event(runtime, payload)

    async def start_full_replay(call: ServiceCall) -> None:
        if not domain_data["entries"]:
            LOGGER.warning("No hay entradas activas de %s", DOMAIN)
            return
        runtime = next(iter(domain_data["entries"].values()))
        payload = {
            "csv_path": str(
                call.data.get("csv_path", "/data/history-1mes_sorted.csv")
            ).strip(),
            "speed_events_per_second": float(
                call.data.get("speed_events_per_second", 30)
            ),
            "debounce_seconds": int(call.data.get("debounce_seconds", 1)),
            "include_all_state_transitions": bool(
                call.data.get("include_all_state_transitions", True)
            ),
            "max_events": int(call.data.get("max_events", 0)),
        }
        try:
            parsed = await post_json(runtime, "/api/replay_csv", payload)
        except Exception as err:  # noqa: BLE001
            runtime["last_error"] = (
                f"No fue posible iniciar replay historico: {err}"
            )
            LOGGER.error(runtime["last_error"])
            raise
        runtime["last_backend_response"] = parsed
        runtime["last_push_at"] = datetime.now(timezone.utc).isoformat()
        runtime["recent_events"].append(
            {
                "timestamp": runtime["last_push_at"],
                "ok": True,
                "entity_id": "service.iniciar_replay_historico",
                "state": "started",
                "room": payload["csv_path"],
                "sensor_type": "service",
            }
        )

    async def refresh_sensor_catalog(_call: ServiceCall) -> None:
        if domain_data["entries"]:
            await refresh_catalog_for_all(hass, domain_data)

    async def create_test_sensors(call: ServiceCall) -> None:
        if not domain_data["entries"]:
            return
        await create_test_sensors_for_all(
            hass,
            domain_data,
            rooms_raw=str(call.data.get("rooms", "")),
            include_occupancy=coerce_bool(
                call.data.get("include_occupancy"), True
            ),
            initial_state=str(call.data.get("initial_state", "off")),
        )

    try:
        hass.services.async_register(
            DOMAIN, SERVICE_EMIT_TEST_EVENT, emit_test_event, schema=TEST_EVENT_SCHEMA
        )
        hass.services.async_register(
            DOMAIN,
            SERVICE_START_FULL_REPLAY,
            start_full_replay,
            schema=FULL_REPLAY_SCHEMA,
        )
        hass.services.async_register(
            DOMAIN,
            SERVICE_REFRESH_SENSOR_CATALOG,
            refresh_sensor_catalog,
            schema=REFRESH_CATALOG_SCHEMA,
        )
        hass.services.async_register(
            DOMAIN,
            SERVICE_CREATE_TEST_SENSORS,
            create_test_sensors,
            schema=CREATE_TEST_SENSORS_SCHEMA,
        )
    except Exception as err:  # noqa: BLE001
        LOGGER.error("No se pudo registrar servicios de %s: %s", DOMAIN, err)
        return
    domain_data["services_registered"] = True


def remove_services(hass: HomeAssistant) -> None:
    for service_name in (
        SERVICE_EMIT_TEST_EVENT,
        SERVICE_START_FULL_REPLAY,
        SERVICE_REFRESH_SENSOR_CATALOG,
        SERVICE_CREATE_TEST_SENSORS,
    ):
        if hass.services.has_service(DOMAIN, service_name):
            hass.services.async_remove(DOMAIN, service_name)
