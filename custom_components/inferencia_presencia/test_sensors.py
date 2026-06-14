"""Administracion de areas y sensores de prueba propios."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.storage import Store

from .catalog import refresh_catalog_for_all
from .const import DOMAIN
from .ha_utils import coerce_bool, safe_room_slug

STORE_VERSION = 1
STORE_KEY = f"{DOMAIN}.test_resources"


def _resources(domain_data: dict[str, Any]) -> dict[str, dict[str, Any]]:
    resources = domain_data.setdefault(
        "test_resources",
        {"areas": {}, "sensors": {}},
    )
    if not isinstance(resources, dict):
        resources = {"areas": {}, "sensors": {}}
        domain_data["test_resources"] = resources
    resources.setdefault("areas", {})
    resources.setdefault("sensors", {})
    return resources


async def load_test_resources(
    hass: HomeAssistant,
    domain_data: dict[str, Any],
) -> None:
    store: Store = Store(
        hass,
        STORE_VERSION,
        STORE_KEY,
        atomic_writes=True,
    )
    domain_data["test_resource_store"] = store
    loaded = await store.async_load()
    if not isinstance(loaded, dict):
        loaded = {"areas": {}, "sensors": {}}
    resources = {
        "areas": dict(loaded.get("areas") or {}),
        "sensors": dict(loaded.get("sensors") or {}),
    }
    domain_data["test_resources"] = resources
    domain_data["test_sensors"] = {
        entity_id: dict(item)
        for entity_id, item in resources["sensors"].items()
        if isinstance(item, dict)
    }


async def _save_test_resources(domain_data: dict[str, Any]) -> None:
    store = domain_data.get("test_resource_store")
    if isinstance(store, Store):
        await store.async_save(_resources(domain_data))


async def upsert_test_switches(
    domain_data: dict[str, Any],
    sensors: list[dict[str, Any]],
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
            "unique_id": str(
                sensor.get("unique_id") or entity_id.replace(".", "_")
            ),
            "name": str(sensor.get("name") or entity_id),
            "room": str(sensor.get("room") or ""),
            "sensor_type": str(sensor.get("sensor_type") or "other"),
            "state": "on"
            if coerce_bool(sensor.get("state"), False)
            else "off",
            "area_id": str(sensor.get("area_id") or ""),
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


async def assign_test_sensor_areas(
    hass: HomeAssistant,
    domain_data: dict[str, Any],
) -> None:
    registry = er.async_get(hass)
    await hass.async_block_till_done()
    for entity_id, item in domain_data.get("test_sensors", {}).items():
        area_id = str(item.get("area_id") or "")
        entry = registry.async_get(entity_id)
        if entry and area_id and entry.area_id != area_id:
            registry.async_update_entity(entity_id, area_id=area_id)


async def create_test_sensors_for_all(
    hass: HomeAssistant,
    domain_data: dict[str, Any],
    *,
    rooms_raw: str,
    include_occupancy: bool,
    initial_state: str,
) -> dict[str, Any]:
    rooms = [
        room
        for item in rooms_raw.split(",")
        if (room := safe_room_slug(item))
    ]
    if not rooms:
        rooms = ["bedroom", "kitchen", "living"]
    initial_state = initial_state.strip().lower() or "off"
    if initial_state not in {"on", "off"}:
        initial_state = "off"
    created_at = datetime.now(timezone.utc).isoformat()
    resources = _resources(domain_data)
    previous_area_ids = set(resources["areas"])
    previous_sensor_ids = set(resources["sensors"])
    area_registry = ar.async_get(hass)
    sensors: list[dict[str, Any]] = []

    area_by_room = {
        str(item.get("room") or ""): area_id
        for area_id, item in resources["areas"].items()
        if isinstance(item, dict)
    }
    for room in rooms:
        area_id = area_by_room.get(room, "")
        if not area_id or area_registry.async_get_area(area_id) is None:
            area = area_registry.async_create(
                f"Inferencia prueba · {room.replace('_', ' ')}"
            )
            area_id = area.id
        resources["areas"][area_id] = {
            "area_id": area_id,
            "room": room,
            "name": f"Inferencia prueba · {room.replace('_', ' ')}",
        }
        definitions = [
            ("motion", initial_state),
            ("door", "off"),
        ]
        if include_occupancy:
            definitions.append(("occupancy", "off"))
        for sensor_type, state in definitions:
            entity_id = f"switch.{DOMAIN}_{room}_{sensor_type}_test"
            sensors.append(
                {
                    "entity_id": entity_id,
                    "unique_id": f"{DOMAIN}_{room}_{sensor_type}_test",
                    "name": f"Inferencia {room} {sensor_type} test",
                    "room": room,
                    "sensor_type": sensor_type,
                    "state": state,
                    "area_id": area_id,
                }
            )

    await upsert_test_switches(domain_data, sensors)
    for sensor in sensors:
        resources["sensors"][sensor["entity_id"]] = dict(sensor)
    await assign_test_sensor_areas(hass, domain_data)
    await _save_test_resources(domain_data)

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
    entries = await refresh_catalog_for_all(hass, domain_data)
    return {
        "entries": entries,
        "created_sensors": sorted(
            set(resources["sensors"]) - previous_sensor_ids
        ),
        "created_areas": sorted(set(resources["areas"]) - previous_area_ids),
        "registered_sensors": sorted(resources["sensors"]),
        "registered_areas": sorted(resources["areas"]),
    }


async def remove_test_resources_for_all(
    hass: HomeAssistant,
    domain_data: dict[str, Any],
    *,
    include_areas: bool,
) -> dict[str, Any]:
    resources = _resources(domain_data)
    entity_registry = er.async_get(hass)
    device_registry = dr.async_get(hass)
    area_registry = ar.async_get(hass)
    entities = domain_data.get("test_switch_entities", {})
    removed_sensors: list[str] = []
    for entity_id in list(resources["sensors"]):
        entity = entities.get(entity_id) if isinstance(entities, dict) else None
        if entity is not None:
            await entity.async_remove(force_remove=True)
        if entity_registry.async_get(entity_id):
            entity_registry.async_remove(entity_id)
        if hass.states.get(entity_id):
            hass.states.async_remove(entity_id)
        domain_data.get("test_sensors", {}).pop(entity_id, None)
        resources["sensors"].pop(entity_id, None)
        removed_sensors.append(entity_id)

    removed_areas: list[str] = []
    preserved_areas: list[str] = []
    if include_areas:
        for area_id in list(resources["areas"]):
            foreign_entities = er.async_entries_for_area(
                entity_registry,
                area_id,
            )
            foreign_devices = dr.async_entries_for_area(
                device_registry,
                area_id,
            )
            if foreign_entities or foreign_devices:
                preserved_areas.append(area_id)
                continue
            if area_registry.async_get_area(area_id):
                area_registry.async_delete(area_id)
            resources["areas"].pop(area_id, None)
            removed_areas.append(area_id)

    await _save_test_resources(domain_data)
    await refresh_catalog_for_all(hass, domain_data)
    return {
        "status": "ok",
        "removed_sensors": removed_sensors,
        "removed_areas": removed_areas,
        "preserved_areas": preserved_areas,
    }
