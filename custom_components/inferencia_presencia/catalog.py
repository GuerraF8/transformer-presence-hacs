"""Descubrimiento y sincronización del catálogo de entidades de Home Assistant."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from homeassistant.core import HomeAssistant, State

from .backend_client import get_json, post_json
from .const import MAX_ENTITY_CATALOG
from .ha_utils import DEFAULT_AUTO_DOMAINS, entity_supported, infer_room, infer_sensor_type
from .runtime import IntegrationRuntime

LOGGER = logging.getLogger(__name__)


def entity_catalog_item(state: State, source: str) -> dict[str, Any]:
    attrs = state.attributes or {}
    sensor_type = str(
        attrs.get("sensor_type") or infer_sensor_type(state.entity_id)
    ).strip().lower()
    room = str(attrs.get("room") or infer_room(state.entity_id)).strip().lower()
    return {
        "entity_id": state.entity_id,
        "name": str(attrs.get("friendly_name") or state.entity_id),
        "domain": state.entity_id.split(".", 1)[0].lower()
        if "." in state.entity_id
        else "",
        "state": state.state,
        "sensor_type": sensor_type,
        "room": room,
        "device_class": str(attrs.get("device_class") or ""),
        "source": source,
        "supported": entity_supported(state.entity_id, sensor_type),
        "last_changed": state.last_changed.isoformat() if state.last_changed else None,
    }


def scan_available_entities(
    hass: HomeAssistant, runtime: IntegrationRuntime
) -> list[dict[str, Any]]:
    catalog: list[dict[str, Any]] = []
    tracked = runtime["tracked_entities"]
    for state in hass.states.async_all():
        if state.attributes.get("inferencia_presencia_output") is True:
            continue
        entity_id = state.entity_id.lower()
        domain = entity_id.split(".", 1)[0]
        source = "auto_domain"
        if runtime["auto_discovery"]:
            if domain not in DEFAULT_AUTO_DOMAINS:
                continue
        elif entity_id not in tracked:
            continue
        else:
            source = "explicit"
        catalog.append(entity_catalog_item(state, source))

    catalog.sort(
        key=lambda item: (
            not item["supported"],
            item["domain"],
            item["room"],
            item["entity_id"],
        )
    )
    return catalog[:MAX_ENTITY_CATALOG]


async def publish_entity_catalog(
    hass: HomeAssistant,
    runtime: IntegrationRuntime,
    source: str = "ha_scan",
) -> None:
    entities = scan_available_entities(hass, runtime)
    scanned_at = datetime.now(timezone.utc).isoformat()
    runtime["available_entities"] = entities
    runtime["available_entities_total"] = len(entities)
    runtime["supported_entities_total"] = sum(
        1 for item in entities if item["supported"]
    )
    runtime["last_scan_at"] = scanned_at
    payload = {
        "source": source,
        "entry_id": runtime["entry_id"],
        "scanned_at": scanned_at,
        "auto_discovery": runtime["auto_discovery"],
        "tracked_entities": sorted(runtime["tracked_entities"]),
        "entities": entities,
    }
    try:
        parsed = await post_json(runtime, "/api/ha_entities", payload, timeout_seconds=8)
    except Exception as err:  # noqa: BLE001
        runtime["last_error"] = f"No fue posible publicar catalogo de sensores: {err!r}"
        LOGGER.error(runtime["last_error"])
        return
    runtime["last_backend_response"] = parsed
    runtime["last_push_at"] = datetime.now(timezone.utc).isoformat()


async def refresh_catalog_for_all(
    hass: HomeAssistant, domain_data: dict[str, Any]
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for entry_id, runtime in domain_data["entries"].items():
        await publish_entity_catalog(hass, runtime, source="ha_ui_refresh")
        results.append(
            {
                "entry_id": entry_id,
                "available_entities_total": runtime["available_entities_total"],
                "supported_entities_total": runtime["supported_entities_total"],
                "last_scan_at": runtime["last_scan_at"],
                "last_error": runtime["last_error"],
            }
        )
    return results


async def publish_entity_catalog_from_cache(
    runtime: IntegrationRuntime, source: str
) -> None:
    entities = runtime.get("available_entities", [])
    if not isinstance(entities, list) or not entities:
        return
    payload = {
        "source": source,
        "entry_id": runtime["entry_id"],
        "scanned_at": runtime.get("last_scan_at")
        or datetime.now(timezone.utc).isoformat(),
        "auto_discovery": runtime["auto_discovery"],
        "tracked_entities": sorted(runtime["tracked_entities"]),
        "entities": entities,
    }
    runtime["last_backend_response"] = await post_json(
        runtime, "/api/ha_entities", payload, timeout_seconds=8
    )
    runtime["last_push_at"] = datetime.now(timezone.utc).isoformat()


async def sync_real_sensor_selection(runtime: IntegrationRuntime) -> None:
    payload = await get_json(runtime, "/api/real_sensor_config", timeout_seconds=8)
    if not isinstance(payload, dict):
        return
    catalog = payload.get("catalog")
    if (
        isinstance(catalog, dict)
        and int(catalog.get("entities_total") or 0) == 0
        and runtime.get("available_entities_total", 0) > 0
    ):
        await publish_entity_catalog_from_cache(runtime, source="ha_backend_resync")
        payload = await get_json(runtime, "/api/real_sensor_config", timeout_seconds=8)
        if not isinstance(payload, dict):
            return
    enabled_entities = payload.get("enabled_entities")
    if not isinstance(enabled_entities, list):
        config = payload.get("config")
        enabled_entities = config.get("enabled_entities") if isinstance(config, dict) else []
    if not isinstance(enabled_entities, list):
        enabled_entities = []
    enabled_set = {
        str(entity_id or "").strip().lower()
        for entity_id in enabled_entities
        if str(entity_id or "").strip()
    }
    local_entities = {
        str(item.get("entity_id") or "").strip().lower()
        for item in runtime.get("available_entities", [])
        if isinstance(item, dict) and str(item.get("entity_id") or "").strip()
    }
    if local_entities:
        enabled_set &= local_entities
    runtime["enabled_real_entities"] = enabled_set
    runtime["last_real_sensor_sync_at"] = datetime.now(timezone.utc).isoformat()
