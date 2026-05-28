from __future__ import annotations

import asyncio
import logging
from collections import deque
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlencode, urljoin

import aiohttp
import voluptuous as vol
from aiohttp import web

from homeassistant.components.http import HomeAssistantView
from homeassistant.components.frontend import (
    async_register_built_in_panel,
    async_remove_panel,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EVENT_STATE_CHANGED
from homeassistant.core import Event, HomeAssistant, ServiceCall, State, callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.typing import ConfigType

from .const import (
    CONF_INFERENCE_API_URL,
    CONF_PANEL_URL,
    CONF_SENSOR_ENTITIES,
    DEFAULT_INFERENCE_API_URL,
    DEFAULT_PANEL_URL,
    DEFAULT_SENSOR_ENTITIES,
    DOMAIN,
    MAX_ENTITY_CATALOG,
    MAX_RECENT_EVENTS,
    PANEL_ICON,
    PANEL_TITLE,
    PANEL_URL_PATH,
    SERVICE_CREATE_TEST_SENSORS,
    SERVICE_EMIT_TEST_EVENT,
    SERVICE_REFRESH_SENSOR_CATALOG,
    SERVICE_START_FULL_REPLAY,
)

LOGGER = logging.getLogger(__name__)

DOMAIN_DEFAULTS: dict[str, Any] = {
    "entries": {},
    "services_registered": False,
    "panel_registered": False,
    "panel_url": None,
    "status_view_registered": False,
}

DEFAULT_AUTO_DOMAINS = {
    "binary_sensor",
    "sensor",
    "person",
    "device_tracker",
    "input_boolean",
    "switch",
    "cover",
    "lock",
}

MOTION_KEYWORDS = {"motion", "pir", "movement", "presence", "detector"}
DOOR_KEYWORDS = {"door", "contact", "window", "gate", "entrance", "entry"}
OCCUPANCY_KEYWORDS = {"occupied", "occupancy", "home", "away", "present"}
ROOM_STOPWORDS = {
    "binary",
    "sensor",
    "device",
    "tracker",
    "input",
    "boolean",
    "status",
    "state",
    "motion",
    "pir",
    "movement",
    "presence",
    "detector",
    "door",
    "contact",
    "window",
    "occupancy",
    "occupied",
    "person",
}

ROOM_ALIASES = {
    "study": "sittingroom",
    "tvroom": "entertainment_room",
    "tv_room": "entertainment_room",
}

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


def _ensure_domain_data(hass: HomeAssistant) -> dict[str, Any]:
    existing = hass.data.get(DOMAIN)
    if isinstance(existing, dict):
        for key, value in DOMAIN_DEFAULTS.items():
            existing.setdefault(key, value if not isinstance(value, dict) else {})
        return existing

    hass.data[DOMAIN] = {
        "entries": {},
        "services_registered": False,
        "panel_registered": False,
        "panel_url": None,
        "status_view_registered": False,
    }
    return hass.data[DOMAIN]


def _tokenize(value: str) -> list[str]:
    normalized = value.replace(".", "_").replace("-", "_").lower()
    return [token for token in normalized.split("_") if token]


def _infer_sensor_type(entity_id: str) -> str:
    domain = entity_id.split(".", 1)[0].lower() if "." in entity_id else ""
    if domain in {"person", "device_tracker"}:
        return "occupancy"

    tokens = set(_tokenize(entity_id))
    if tokens & DOOR_KEYWORDS:
        return "door"
    if tokens & OCCUPANCY_KEYWORDS:
        return "occupancy"
    if tokens & MOTION_KEYWORDS:
        return "motion"
    return "other"


def _infer_room(entity_id: str) -> str:
    object_id = entity_id.split(".", 1)[1] if "." in entity_id else entity_id
    tokens = _tokenize(object_id)
    useful = [token for token in tokens if token not in ROOM_STOPWORDS]
    if useful:
        room = "_".join(useful)
    else:
        room = object_id.lower().replace(".", "_")
    return ROOM_ALIASES.get(room, room)


def _parse_tracked_entities(raw_value: str) -> set[str]:
    if not raw_value:
        return set()
    return {item.strip().lower() for item in raw_value.split(",") if item.strip()}


def _build_url(base_url: str, path: str) -> str:
    base = base_url.rstrip("/") + "/"
    return urljoin(base, path.lstrip("/"))


def _panel_url_from_backend(base_url: str) -> str:
    return f"{base_url.rstrip('/')}/?embedded=1"


def _resolve_panel_url(panel_url: str, backend_url: str) -> str:
    return _panel_url_from_backend(panel_url or backend_url)


def _entity_supported(entity_id: str, sensor_type: str) -> bool:
    domain = entity_id.split(".", 1)[0].lower() if "." in entity_id else ""
    return domain in DEFAULT_AUTO_DOMAINS and sensor_type in {"motion", "door", "occupancy"}


def _entity_catalog_item(state: State, source: str) -> dict[str, Any]:
    sensor_type = _infer_sensor_type(state.entity_id)
    attrs = state.attributes or {}
    name = str(attrs.get("friendly_name") or state.entity_id)
    device_class = str(attrs.get("device_class") or "")
    return {
        "entity_id": state.entity_id,
        "name": name,
        "domain": state.entity_id.split(".", 1)[0].lower() if "." in state.entity_id else "",
        "state": state.state,
        "sensor_type": sensor_type,
        "room": _infer_room(state.entity_id),
        "device_class": device_class,
        "source": source,
        "supported": _entity_supported(state.entity_id, sensor_type),
        "last_changed": state.last_changed.isoformat() if state.last_changed else None,
    }


def _scan_available_entities(hass: HomeAssistant, runtime: dict[str, Any]) -> list[dict[str, Any]]:
    catalog: list[dict[str, Any]] = []
    tracked = runtime["tracked_entities"]

    for state in hass.states.async_all():
        entity_id = state.entity_id.lower()
        domain = entity_id.split(".", 1)[0]
        source = "auto_domain"
        if runtime["auto_discovery"]:
            if domain not in DEFAULT_AUTO_DOMAINS:
                continue
        else:
            if entity_id not in tracked:
                continue
            source = "explicit"

        catalog.append(_entity_catalog_item(state, source))

    catalog.sort(key=lambda item: (not item["supported"], item["domain"], item["room"], item["entity_id"]))
    return catalog[:MAX_ENTITY_CATALOG]


async def _publish_entity_catalog(
    hass: HomeAssistant,
    runtime: dict[str, Any],
    source: str = "ha_scan",
) -> None:
    entities = _scan_available_entities(hass, runtime)
    scanned_at = datetime.now(timezone.utc).isoformat()
    runtime["available_entities"] = entities
    runtime["available_entities_total"] = len(entities)
    runtime["supported_entities_total"] = len([item for item in entities if item["supported"]])
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
        parsed = await _post_backend_json(runtime, "/api/ha_entities", payload, timeout_seconds=8)
    except Exception as err:  # noqa: BLE001
        runtime["last_error"] = f"No fue posible publicar catalogo de sensores: {err!r}"
        LOGGER.error(runtime["last_error"])
        return

    runtime["last_backend_response"] = parsed
    runtime["last_push_at"] = datetime.now(timezone.utc).isoformat()


class InferenciaPresenciaStatusView(HomeAssistantView):
    url = "/api/inferencia_presencia/status"
    name = "api:inferencia_presencia:status"
    requires_auth = True

    def __init__(self, domain_data: dict[str, Any]) -> None:
        self._domain_data = domain_data

    async def get(self, request) -> web.Response:
        entries = []
        for entry_id, runtime in self._domain_data["entries"].items():
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
                }
            )

        return web.json_response(
            {
                "domain": DOMAIN,
                "panel_url": self._domain_data.get("panel_url"),
                "entries": entries,
            }
        )


async def _refresh_catalog_for_all(hass: HomeAssistant, domain_data: dict[str, Any]) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for entry_id, runtime in domain_data["entries"].items():
        await _publish_entity_catalog(hass, runtime, source="ha_ui_refresh")
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


def _coerce_bool(value: Any, fallback: bool = True) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return fallback
    normalized = str(value).strip().lower()
    if normalized in {"1", "true", "yes", "on", "incluir"}:
        return True
    if normalized in {"0", "false", "no", "off", "omitir"}:
        return False
    return fallback


async def _create_test_sensors_for_all(
    hass: HomeAssistant,
    domain_data: dict[str, Any],
    *,
    rooms_raw: str,
    include_occupancy: bool,
    initial_state: str,
) -> list[dict[str, Any]]:
    rooms = [
        item.strip().lower().replace(" ", "_")
        for item in rooms_raw.split(",")
        if item.strip()
    ]
    if not rooms:
        rooms = ["bedroom", "kitchen", "living"]

    initial_state = initial_state.strip().lower() or "off"
    if initial_state not in {"on", "off"}:
        initial_state = "off"
    created_at = datetime.now(timezone.utc).isoformat()

    for room in rooms:
        hass.states.async_set(
            f"binary_sensor.{DOMAIN}_{room}_motion_test",
            initial_state,
            {
                "friendly_name": f"Inferencia {room} motion test",
                "device_class": "motion",
                "inferencia_presencia_test": True,
                "room": room,
            },
        )
        hass.states.async_set(
            f"binary_sensor.{DOMAIN}_{room}_door_test",
            "off",
            {
                "friendly_name": f"Inferencia {room} door test",
                "device_class": "door",
                "inferencia_presencia_test": True,
                "room": room,
            },
        )
        if include_occupancy:
            hass.states.async_set(
                f"input_boolean.{DOMAIN}_{room}_occupancy_test",
                "off",
                {
                    "friendly_name": f"Inferencia {room} occupancy test",
                    "inferencia_presencia_test": True,
                    "room": room,
                },
            )

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

    return await _refresh_catalog_for_all(hass, domain_data)


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
            results = await _refresh_catalog_for_all(self._hass, self._domain_data)
            return web.json_response({"status": "ok", "action": action, "entries": results})

        if action == "create_test_sensors":
            results = await _create_test_sensors_for_all(
                self._hass,
                self._domain_data,
                rooms_raw=str(payload.get("rooms", "bedroom,kitchen,living")),
                include_occupancy=_coerce_bool(payload.get("include_occupancy"), True),
                initial_state=str(payload.get("initial_state", "off")),
            )
            return web.json_response({"status": "ok", "action": action, "entries": results})

        return web.json_response(
            {"status": "error", "error": f"accion no soportada: {action}"},
            status=400,
        )


async def _forward_payload(
    runtime: dict[str, Any],
    payload: dict[str, Any],
) -> None:
    endpoint = _build_url(runtime["backend_url"], "/api/events")
    session = runtime["http_session"]
    timeout = aiohttp.ClientTimeout(total=10)

    try:
        async with session.post(endpoint, json=payload, timeout=timeout) as response:
            body = await response.text()
            if response.status >= 400:
                runtime["failed_events"] += 1
                runtime["last_error"] = (
                    f"Backend retorno {response.status} para {payload['entity_id']}: {body}"
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
                    if isinstance(maybe_json, dict):
                        parsed = maybe_json
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


async def _post_backend_json(
    runtime: dict[str, Any],
    path: str,
    payload: dict[str, Any],
    timeout_seconds: float = 60,
) -> dict[str, Any] | None:
    endpoint = _build_url(runtime["backend_url"], path)
    session = runtime["http_session"]
    timeout = aiohttp.ClientTimeout(total=timeout_seconds)

    async with session.post(endpoint, json=payload, timeout=timeout) as response:
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


async def _get_backend_json(
    runtime: dict[str, Any],
    path: str,
    timeout_seconds: float = 8,
) -> dict[str, Any] | None:
    endpoint = _build_url(runtime["backend_url"], path)
    session = runtime["http_session"]
    timeout = aiohttp.ClientTimeout(total=timeout_seconds)

    async with session.get(endpoint, timeout=timeout) as response:
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


async def _execute_backend_action(
    hass: HomeAssistant,
    domain_data: dict[str, Any],
    action_request: dict[str, Any],
) -> dict[str, Any]:
    action = str(action_request.get("action", "")).strip()
    payload = action_request.get("payload") if isinstance(action_request.get("payload"), dict) else {}

    if action == "refresh_catalog":
        entries = await _refresh_catalog_for_all(hass, domain_data)
        return {"status": "ok", "action": action, "entries": entries}

    if action == "create_test_sensors":
        entries = await _create_test_sensors_for_all(
            hass,
            domain_data,
            rooms_raw=str(payload.get("rooms", "bedroom,kitchen,living")),
            include_occupancy=_coerce_bool(payload.get("include_occupancy"), True),
            initial_state=str(payload.get("initial_state", "off")),
        )
        return {"status": "ok", "action": action, "entries": entries}

    return {"status": "error", "action": action, "error": "accion no soportada"}


async def _publish_integration_status(runtime: dict[str, Any], *, poller_state: str) -> None:
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
    }
    await _post_backend_json(runtime, "/api/ha_integration_status", payload, timeout_seconds=8)


async def _poll_backend_actions(
    hass: HomeAssistant,
    domain_data: dict[str, Any],
    runtime: dict[str, Any],
) -> None:
    while True:
        await asyncio.sleep(2)
        request_id = ""
        try:
            await _publish_integration_status(runtime, poller_state="polling")
            query = urlencode({"entry_id": runtime["entry_id"]})
            action_request = await _get_backend_json(runtime, f"/api/ha_actions/pending?{query}")
            if not action_request or action_request.get("status") == "empty":
                continue

            request_id = str(action_request.get("request_id", ""))
            result = await _execute_backend_action(hass, domain_data, action_request)
            if request_id:
                await _post_backend_json(
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
            await _publish_integration_status(runtime, poller_state="executed_action")
        except asyncio.CancelledError:
            raise
        except Exception as err:  # noqa: BLE001
            runtime["last_error"] = f"No fue posible ejecutar accion solicitada desde UI: {err!r}"
            LOGGER.error(runtime["last_error"])
            if request_id:
                try:
                    await _post_backend_json(
                        runtime,
                        f"/api/ha_actions/{request_id}/result",
                        {"status": "error", "error": str(err)},
                        timeout_seconds=8,
                    )
                except Exception:  # noqa: BLE001
                    LOGGER.debug("No se pudo reportar error de accion HA al backend", exc_info=True)


async def _process_state_change(
    runtime: dict[str, Any],
    new_state: State,
    old_state: State | None,
    source: str,
) -> None:
    if old_state is not None and old_state.state == new_state.state:
        return

    if new_state.state.lower() in {"unknown", "unavailable"}:
        return

    payload = {
        "entity_id": new_state.entity_id,
        "state": new_state.state,
        "sensor_type": _infer_sensor_type(new_state.entity_id),
        "room": _infer_room(new_state.entity_id),
        "timestamp": new_state.last_changed.isoformat(),
        "source": source,
    }
    await _forward_payload(runtime, payload)


def _register_panel(
    hass: HomeAssistant,
    domain_data: dict[str, Any],
    backend_url: str,
    panel_base_url: str = "",
) -> None:
    panel_url = _resolve_panel_url(panel_base_url, backend_url)

    if (
        domain_data.get("panel_registered")
        and domain_data.get("panel_url") == panel_url
    ):
        return

    try:
        if domain_data.get("panel_registered"):
            async_remove_panel(hass, PANEL_URL_PATH)

        async_register_built_in_panel(
            hass,
            component_name="iframe",
            frontend_url_path=PANEL_URL_PATH,
            config={"url": panel_url},
            sidebar_title=PANEL_TITLE,
            sidebar_icon=PANEL_ICON,
            require_admin=False,
        )
    except Exception as err:  # noqa: BLE001
        LOGGER.error("No se pudo registrar panel de %s: %s", DOMAIN, err)
        return

    domain_data["panel_registered"] = True
    domain_data["panel_url"] = panel_url


def _register_status_view(hass: HomeAssistant, domain_data: dict[str, Any]) -> None:
    if domain_data.get("status_view_registered"):
        return

    if not hasattr(hass, "http"):
        LOGGER.warning("No se pudo registrar vista de estado de %s: HTTP no disponible", DOMAIN)
        return

    try:
        hass.http.register_view(InferenciaPresenciaStatusView(domain_data))
        hass.http.register_view(InferenciaPresenciaActionsView(hass, domain_data))
    except Exception as err:  # noqa: BLE001
        LOGGER.error("No se pudo registrar vista de estado de %s: %s", DOMAIN, err)
        return

    domain_data["status_view_registered"] = True


def _create_background_task(
    hass: HomeAssistant,
    entry: ConfigEntry,
    coro,
    name: str,
):
    create_background_task = getattr(entry, "async_create_background_task", None)
    if create_background_task is not None:
        return create_background_task(hass, coro, name)
    return hass.loop.create_task(coro, name=name)


async def _ensure_services(hass: HomeAssistant, domain_data: dict[str, Any]) -> None:
    if domain_data.get("services_registered"):
        return

    service_names = [
        SERVICE_EMIT_TEST_EVENT,
        SERVICE_START_FULL_REPLAY,
        SERVICE_REFRESH_SENSOR_CATALOG,
        SERVICE_CREATE_TEST_SENSORS,
    ]
    if all(hass.services.has_service(DOMAIN, service_name) for service_name in service_names):
        domain_data["services_registered"] = True
        return
    for service_name in service_names:
        if hass.services.has_service(DOMAIN, service_name):
            hass.services.async_remove(DOMAIN, service_name)

    async def _emit_test_event(call: ServiceCall) -> None:
        if not domain_data["entries"]:
            LOGGER.warning("No hay entradas activas de %s para enviar evento de prueba", DOMAIN)
            return

        first_runtime = next(iter(domain_data["entries"].values()))

        room = str(call.data["room"]).strip().lower()
        sensor_type = str(call.data.get("sensor_type", "motion")).strip().lower()
        state = str(call.data.get("state", "on")).strip().lower()

        entity_id = str(call.data.get("entity_id", "")).strip().lower()
        if not entity_id:
            entity_id = f"simulated_sensor.{room}_{sensor_type}"

        timestamp = str(call.data.get("timestamp", "")).strip()

        payload: dict[str, Any] = {
            "entity_id": entity_id,
            "state": state,
            "sensor_type": sensor_type,
            "room": room,
            "source": "ha_test_service",
        }
        if timestamp:
            payload["timestamp"] = timestamp

        await _forward_payload(first_runtime, payload)

    async def _start_full_replay(call: ServiceCall) -> None:
        if not domain_data["entries"]:
            LOGGER.warning("No hay entradas activas de %s para iniciar replay", DOMAIN)
            return

        first_runtime = next(iter(domain_data["entries"].values()))
        payload = {
            "csv_path": str(call.data.get("csv_path", "/data/history-1mes_sorted.csv")).strip(),
            "speed_events_per_second": float(call.data.get("speed_events_per_second", 30)),
            "debounce_seconds": int(call.data.get("debounce_seconds", 1)),
            "include_all_state_transitions": bool(
                call.data.get("include_all_state_transitions", True)
            ),
            "max_events": int(call.data.get("max_events", 0)),
        }

        try:
            parsed = await _post_backend_json(first_runtime, "/api/replay_csv", payload)
        except Exception as err:  # noqa: BLE001
            first_runtime["last_error"] = f"No fue posible iniciar replay historico: {err}"
            LOGGER.error(first_runtime["last_error"])
            raise

        first_runtime["last_backend_response"] = parsed
        first_runtime["last_push_at"] = datetime.now(timezone.utc).isoformat()
        first_runtime["recent_events"].append(
            {
                "timestamp": first_runtime["last_push_at"],
                "ok": True,
                "entity_id": "service.iniciar_replay_historico",
                "state": "started",
                "room": payload["csv_path"],
                "sensor_type": "service",
            }
        )

    async def _refresh_sensor_catalog(call: ServiceCall) -> None:
        if not domain_data["entries"]:
            LOGGER.warning("No hay entradas activas de %s para refrescar catalogo", DOMAIN)
            return

        await _refresh_catalog_for_all(hass, domain_data)

    async def _create_test_sensors(call: ServiceCall) -> None:
        if not domain_data["entries"]:
            LOGGER.warning("No hay entradas activas de %s para crear sensores de prueba", DOMAIN)
            return

        await _create_test_sensors_for_all(
            hass,
            domain_data,
            rooms_raw=str(call.data.get("rooms", "")),
            include_occupancy=_coerce_bool(call.data.get("include_occupancy"), True),
            initial_state=str(call.data.get("initial_state", "off")),
        )

    try:
        hass.services.async_register(
            DOMAIN,
            SERVICE_EMIT_TEST_EVENT,
            _emit_test_event,
            schema=TEST_EVENT_SCHEMA,
        )
        hass.services.async_register(
            DOMAIN,
            SERVICE_START_FULL_REPLAY,
            _start_full_replay,
            schema=FULL_REPLAY_SCHEMA,
        )
        hass.services.async_register(
            DOMAIN,
            SERVICE_REFRESH_SENSOR_CATALOG,
            _refresh_sensor_catalog,
            schema=REFRESH_CATALOG_SCHEMA,
        )
        hass.services.async_register(
            DOMAIN,
            SERVICE_CREATE_TEST_SENSORS,
            _create_test_sensors,
            schema=CREATE_TEST_SENSORS_SCHEMA,
        )
    except Exception as err:  # noqa: BLE001
        LOGGER.error("No se pudo registrar servicios de %s: %s", DOMAIN, err)
        return

    domain_data["services_registered"] = True


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    _ensure_domain_data(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    domain_data = _ensure_domain_data(hass)
    _register_status_view(hass, domain_data)
    await _ensure_services(hass, domain_data)

    backend_url = (
        str(
            entry.options.get(
                CONF_INFERENCE_API_URL,
                entry.data.get(CONF_INFERENCE_API_URL, DEFAULT_INFERENCE_API_URL),
            )
        ).strip()
    )
    panel_base_url = (
        str(
            entry.options.get(
                CONF_PANEL_URL,
                entry.data.get(CONF_PANEL_URL, DEFAULT_PANEL_URL),
            )
        ).strip()
    )
    sensor_entities_raw = str(
        entry.options.get(
            CONF_SENSOR_ENTITIES,
            entry.data.get(CONF_SENSOR_ENTITIES, DEFAULT_SENSOR_ENTITIES),
        )
    ).strip()
    tracked_entities = _parse_tracked_entities(sensor_entities_raw)

    runtime: dict[str, Any] = {
        "entry_id": entry.entry_id,
        "backend_url": backend_url or DEFAULT_INFERENCE_API_URL,
        "panel_base_url": panel_base_url,
        "tracked_entities": tracked_entities,
        "auto_discovery": len(tracked_entities) == 0,
        "http_session": async_get_clientsession(hass),
        "unsub": None,
        "action_poll_task": None,
        "last_event": None,
        "last_backend_response": None,
        "last_error": None,
        "last_push_at": None,
        "last_scan_at": None,
        "available_entities": [],
        "available_entities_total": 0,
        "supported_entities_total": 0,
        "recent_events": deque(maxlen=MAX_RECENT_EVENTS),
        "sent_events": 0,
        "failed_events": 0,
    }

    @callback
    def _handle_state_event(event: Event) -> None:
        new_state = event.data.get("new_state")
        old_state = event.data.get("old_state")

        if new_state is None:
            return

        if runtime["auto_discovery"]:
            domain = new_state.entity_id.split(".", 1)[0].lower()
            if domain not in DEFAULT_AUTO_DOMAINS:
                return
        elif new_state.entity_id.lower() not in runtime["tracked_entities"]:
            return

        hass.async_create_task(
            _process_state_change(
                runtime,
                new_state,
                old_state,
                source="ha_state_change",
            )
        )

    domain_data["entries"][entry.entry_id] = runtime
    await _publish_entity_catalog(hass, runtime, source="ha_startup_scan")
    runtime["action_poll_task"] = _create_background_task(
        hass,
        entry,
        _poll_backend_actions(hass, domain_data, runtime),
        f"{DOMAIN}_action_poll",
    )

    if runtime["auto_discovery"]:
        runtime["unsub"] = hass.bus.async_listen(EVENT_STATE_CHANGED, _handle_state_event)
    else:
        runtime["unsub"] = async_track_state_change_event(
            hass,
            list(runtime["tracked_entities"]),
            _handle_state_event,
        )

    entry.async_on_unload(entry.add_update_listener(async_reload_entry))
    _register_panel(hass, domain_data, runtime["backend_url"], runtime["panel_base_url"])

    LOGGER.info(
        "Integracion %s iniciada. Backend: %s | auto_discovery=%s | tracked=%s",
        DOMAIN,
        runtime["backend_url"],
        runtime["auto_discovery"],
        sorted(runtime["tracked_entities"]),
    )

    return True


async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await async_unload_entry(hass, entry)
    await async_setup_entry(hass, entry)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    domain_data = _ensure_domain_data(hass)
    runtime = domain_data["entries"].pop(entry.entry_id, None)

    if runtime and runtime.get("unsub"):
        runtime["unsub"]()
    if runtime and runtime.get("action_poll_task"):
        runtime["action_poll_task"].cancel()

    if domain_data["entries"]:
        first_runtime = next(iter(domain_data["entries"].values()))
        _register_panel(
            hass,
            domain_data,
            first_runtime["backend_url"],
            first_runtime.get("panel_base_url", ""),
        )
        return True

    if domain_data.get("panel_registered"):
        async_remove_panel(hass, PANEL_URL_PATH)
        domain_data["panel_registered"] = False
        domain_data["panel_url"] = None

    if hass.services.has_service(DOMAIN, SERVICE_EMIT_TEST_EVENT):
        hass.services.async_remove(DOMAIN, SERVICE_EMIT_TEST_EVENT)
    if hass.services.has_service(DOMAIN, SERVICE_START_FULL_REPLAY):
        hass.services.async_remove(DOMAIN, SERVICE_START_FULL_REPLAY)
    if hass.services.has_service(DOMAIN, SERVICE_REFRESH_SENSOR_CATALOG):
        hass.services.async_remove(DOMAIN, SERVICE_REFRESH_SENSOR_CATALOG)
    if hass.services.has_service(DOMAIN, SERVICE_CREATE_TEST_SENSORS):
        hass.services.async_remove(DOMAIN, SERVICE_CREATE_TEST_SENSORS)
    domain_data["services_registered"] = False

    return True
