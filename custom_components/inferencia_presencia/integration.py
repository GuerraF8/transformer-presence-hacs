"""Ciclo de vida de las entradas de configuración de Inferencia de presencia."""

from __future__ import annotations

import asyncio
import logging
import secrets
from collections import deque
from contextlib import suppress
from typing import Any

from homeassistant.components.frontend import async_remove_panel
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EVENT_STATE_CHANGED, Platform
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.area_registry import EVENT_AREA_REGISTRY_UPDATED
from homeassistant.helpers.device_registry import EVENT_DEVICE_REGISTRY_UPDATED
from homeassistant.helpers.entity_registry import EVENT_ENTITY_REGISTRY_UPDATED
from homeassistant.helpers.typing import ConfigType

from .actions import poll_backend_actions
from .backend_client import get_json
from .catalog import publish_entity_catalog, sync_real_sensor_selection
from .const import (
    CONF_DEV_MODE,
    CONF_INFERENCE_API_URL,
    CONF_PANEL_URL,
    CONF_SENSOR_ENTITIES,
    DEFAULT_DEV_MODE,
    DEFAULT_INFERENCE_API_URL,
    DEFAULT_PANEL_URL,
    DEFAULT_SENSOR_ENTITIES,
    DOMAIN,
    MAX_RECENT_EVENTS,
    PANEL_URL_PATH,
)
from .coordinator import PresenceDataUpdateCoordinator
from .domain_data import ensure_domain_data
from .event_forwarding import process_state_change
from .ha_utils import parse_tracked_entities
from .panel import register_panel
from .runtime import IntegrationRuntime
from .services import ensure_services, remove_services
from .views import register_status_views
from .test_sensors import assign_test_sensor_areas, load_test_resources

LOGGER = logging.getLogger(__name__)
PLATFORMS = [Platform.BINARY_SENSOR, Platform.SENSOR, Platform.SWITCH]


def _entry_value(
    entry: ConfigEntry, key: str, default: Any
) -> Any:
    return entry.options.get(key, entry.data.get(key, default))


def _create_runtime(
    hass: HomeAssistant, entry: ConfigEntry
) -> IntegrationRuntime:
    tracked_entities = parse_tracked_entities(
        str(_entry_value(entry, CONF_SENSOR_ENTITIES, DEFAULT_SENSOR_ENTITIES)).strip()
    )
    return {
        "entry_id": entry.entry_id,
        "backend_url": str(
            _entry_value(entry, CONF_INFERENCE_API_URL, DEFAULT_INFERENCE_API_URL)
        ).strip()
        or DEFAULT_INFERENCE_API_URL,
        "panel_base_url": str(
            _entry_value(entry, CONF_PANEL_URL, DEFAULT_PANEL_URL)
        ).strip(),
        "panel_token": secrets.token_urlsafe(32),
        "dev_mode": bool(_entry_value(entry, CONF_DEV_MODE, DEFAULT_DEV_MODE)),
        "tracked_entities": tracked_entities,
        "auto_discovery": not tracked_entities,
        "http_session": async_get_clientsession(hass),
        "unsub": None,
        "action_poll_task": None,
        "last_event": None,
        "last_backend_response": None,
        "last_error": None,
        "last_push_at": None,
        "last_scan_at": None,
        "available_entities": [],
        "available_areas": [],
        "available_entities_total": 0,
        "supported_entities_total": 0,
        "enabled_real_entities": set(),
        "last_real_sensor_sync_at": None,
        "recent_events": deque(maxlen=MAX_RECENT_EVENTS),
        "sent_events": 0,
        "failed_events": 0,
        "registry_unsubs": [],
        "catalog_refresh_task": None,
    }


def _create_background_task(
    hass: HomeAssistant,
    entry: ConfigEntry,
    coro,
    name: str,
):
    create_task = getattr(entry, "async_create_background_task", None)
    if create_task is not None:
        return create_task(hass, coro, name)
    return hass.loop.create_task(coro, name=name)


def _subscribe_state_events(
    hass: HomeAssistant, runtime: IntegrationRuntime
):
    @callback
    def handle_state_event(event: Event) -> None:
        new_state = event.data.get("new_state")
        old_state = event.data.get("old_state")
        if new_state is None:
            return
        if new_state.attributes.get("inferencia_presencia_output") is True:
            return
        entity_id = new_state.entity_id.lower()
        if entity_id not in runtime.get("enabled_real_entities", set()):
            return
        hass.async_create_task(
            process_state_change(
                runtime,
                new_state,
                old_state,
                source="ha_state_change",
            )
        )

    return hass.bus.async_listen(EVENT_STATE_CHANGED, handle_state_event)


def _subscribe_registry_events(
    hass: HomeAssistant,
    runtime: IntegrationRuntime,
) -> list[Any]:
    @callback
    def schedule_catalog_refresh(_event: Event) -> None:
        current = runtime.get("catalog_refresh_task")
        if current and not current.done():
            current.cancel()

        async def delayed_refresh() -> None:
            await asyncio.sleep(1)
            await publish_entity_catalog(
                hass,
                runtime,
                source="ha_registry_update",
            )
            await sync_real_sensor_selection(runtime)

        runtime["catalog_refresh_task"] = hass.async_create_task(
            delayed_refresh()
        )

    return [
        hass.bus.async_listen(event_type, schedule_catalog_refresh)
        for event_type in (
            EVENT_AREA_REGISTRY_UPDATED,
            EVENT_DEVICE_REGISTRY_UPDATED,
            EVENT_ENTITY_REGISTRY_UPDATED,
        )
    ]


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    domain_data = ensure_domain_data(hass)
    register_status_views(hass, domain_data)
    await ensure_services(hass, domain_data)
    return True


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry
) -> bool:
    domain_data = ensure_domain_data(hass)
    register_status_views(hass, domain_data)
    await ensure_services(hass, domain_data)
    runtime = _create_runtime(hass, entry)

    async def fetch_presence_snapshot() -> dict[str, Any] | None:
        return await get_json(runtime, "/api/sim_data", timeout_seconds=8)

    runtime["coordinator"] = PresenceDataUpdateCoordinator(
        hass, fetch_presence_snapshot
    )
    entry.runtime_data = runtime
    previous_runtime = domain_data["entries"].get(entry.entry_id)
    if previous_runtime:
        domain_data["panel_tokens"].pop(
            previous_runtime.get("panel_token"),
            None,
        )
    domain_data["entries"][entry.entry_id] = runtime
    domain_data["panel_tokens"][runtime["panel_token"]] = runtime

    try:
        if domain_data.get("test_resource_store") is None:
            await load_test_resources(hass, domain_data)
        await runtime["coordinator"].async_config_entry_first_refresh()
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
        await assign_test_sensor_areas(hass, domain_data)
        await publish_entity_catalog(hass, runtime, source="ha_startup_scan")
    except BaseException:
        if domain_data["entries"].get(entry.entry_id) is runtime:
            domain_data["entries"].pop(entry.entry_id, None)
        domain_data["panel_tokens"].pop(runtime["panel_token"], None)
        raise
    try:
        await sync_real_sensor_selection(runtime)
    except Exception as err:  # noqa: BLE001
        runtime["last_error"] = (
            f"No fue posible sincronizar seleccion de sensores reales: {err!r}"
        )
        LOGGER.warning(runtime["last_error"])

    runtime["action_poll_task"] = _create_background_task(
        hass,
        entry,
        poll_backend_actions(hass, domain_data, runtime),
        f"{DOMAIN}_action_poll",
    )
    runtime["unsub"] = _subscribe_state_events(hass, runtime)
    runtime["registry_unsubs"] = _subscribe_registry_events(hass, runtime)
    entry.async_on_unload(entry.add_update_listener(async_reload_entry))
    register_panel(
        hass,
        domain_data,
        runtime["backend_url"],
        runtime["panel_base_url"],
        runtime["dev_mode"],
        runtime["panel_token"],
    )
    LOGGER.info(
        "Integracion %s iniciada. Backend: %s | auto_discovery=%s | tracked=%s",
        DOMAIN,
        runtime["backend_url"],
        runtime["auto_discovery"],
        sorted(runtime["tracked_entities"]),
    )
    return True


async def async_reload_entry(
    hass: HomeAssistant, entry: ConfigEntry
) -> None:
    await async_unload_entry(hass, entry)
    await async_setup_entry(hass, entry)


async def async_unload_entry(
    hass: HomeAssistant, entry: ConfigEntry
) -> bool:
    domain_data = ensure_domain_data(hass)
    runtime = domain_data["entries"].pop(entry.entry_id, None)
    if runtime:
        domain_data["panel_tokens"].pop(runtime["panel_token"], None)
    if runtime and runtime.get("unsub"):
        runtime["unsub"]()
    if runtime:
        for unsub in runtime.get("registry_unsubs", []):
            unsub()
        refresh_task = runtime.get("catalog_refresh_task")
        if refresh_task and not refresh_task.done():
            refresh_task.cancel()
            with suppress(asyncio.CancelledError):
                await refresh_task
    if runtime and runtime.get("action_poll_task"):
        task = runtime["action_poll_task"]
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task

    await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if domain_data["entries"]:
        first_runtime = next(iter(domain_data["entries"].values()))
        register_panel(
            hass,
            domain_data,
            first_runtime["backend_url"],
            first_runtime.get("panel_base_url", ""),
            first_runtime.get("dev_mode", DEFAULT_DEV_MODE),
            first_runtime["panel_token"],
        )
        return True

    if domain_data.get("panel_registered"):
        async_remove_panel(hass, PANEL_URL_PATH)
        domain_data["panel_registered"] = False
        domain_data["panel_url"] = None
    remove_services(hass)
    domain_data["services_registered"] = False
    return True
