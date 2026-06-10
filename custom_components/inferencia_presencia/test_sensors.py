"""Creación y publicación de interruptores para sensores de prueba."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any

from homeassistant.core import HomeAssistant

from .catalog import refresh_catalog_for_all
from .const import DOMAIN
from .ha_utils import coerce_bool, safe_room_slug


async def upsert_test_switches(
    domain_data: dict[str, Any], sensors: list[dict[str, Any]]
) -> None:
    store = domain_data.setdefault("test_sensors", {})
    if not isinstance(store, dict):
        store = {}
        domain_data["test_sensors"] = store
    new_items: list[dict[str, Any]] = []
    for sensor in sensors:
        entity_id = str(sensor.get("entity_id") or "").strip().lower()
        if not entity_id:
            continue
        item = {
            "entity_id": entity_id,
            "unique_id": str(sensor.get("unique_id") or entity_id.replace(".", "_")),
            "name": str(sensor.get("name") or entity_id),
            "room": str(sensor.get("room") or ""),
            "sensor_type": str(sensor.get("sensor_type") or "other"),
            "state": "on" if coerce_bool(sensor.get("state"), False) else "off",
        }
        if entity_id not in store:
            new_items.append(item)
        store[entity_id] = item

    adders = domain_data.get("test_switch_adders")
    if not new_items or not isinstance(adders, dict):
        return
    for async_add_entities in list(adders.values()):
        async_add_entities([item.copy() for item in new_items])
    await asyncio.sleep(0)


async def create_test_sensors_for_all(
    hass: HomeAssistant,
    domain_data: dict[str, Any],
    *,
    rooms_raw: str,
    include_occupancy: bool,
    initial_state: str,
) -> list[dict[str, Any]]:
    rooms = [room for item in rooms_raw.split(",") if (room := safe_room_slug(item))]
    if not rooms:
        rooms = ["bedroom", "kitchen", "living"]
    initial_state = initial_state.strip().lower() or "off"
    if initial_state not in {"on", "off"}:
        initial_state = "off"
    created_at = datetime.now(timezone.utc).isoformat()
    sensors: list[dict[str, Any]] = []

    for room in rooms:
        sensors.extend(
            [
                {
                    "entity_id": f"switch.{DOMAIN}_{room}_motion_test",
                    "unique_id": f"{DOMAIN}_{room}_motion_test",
                    "name": f"Inferencia {room} motion test",
                    "room": room,
                    "sensor_type": "motion",
                    "state": initial_state,
                },
                {
                    "entity_id": f"switch.{DOMAIN}_{room}_door_test",
                    "unique_id": f"{DOMAIN}_{room}_door_test",
                    "name": f"Inferencia {room} door test",
                    "room": room,
                    "sensor_type": "door",
                    "state": "off",
                },
            ]
        )
        if include_occupancy:
            sensors.append(
                {
                    "entity_id": f"switch.{DOMAIN}_{room}_occupancy_test",
                    "unique_id": f"{DOMAIN}_{room}_occupancy_test",
                    "name": f"Inferencia {room} occupancy test",
                    "room": room,
                    "sensor_type": "occupancy",
                    "state": "off",
                }
            )
        for legacy_entity_id in (
            f"binary_sensor.{DOMAIN}_{room}_motion_test",
            f"binary_sensor.{DOMAIN}_{room}_door_test",
            f"input_boolean.{DOMAIN}_{room}_occupancy_test",
        ):
            legacy_state = hass.states.get(legacy_entity_id)
            if legacy_state and legacy_state.attributes.get(
                "inferencia_presencia_test"
            ) is True:
                hass.states.async_remove(legacy_entity_id)

    await upsert_test_switches(domain_data, sensors)
    for runtime in domain_data["entries"].values():
        runtime["recent_events"].append(
            {
                "timestamp": created_at,
                "ok": True,
                "entity_id": "ui.crear_sensores_prueba",
                "state": "created",
                "room": ",".join(rooms),
                "sensor_type": "service",
            }
        )
    return await refresh_catalog_for_all(hass, domain_data)
