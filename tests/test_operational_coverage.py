from __future__ import annotations

import asyncio
from collections import deque
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
import pytest
from homeassistant.const import STATE_OFF, STATE_ON
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.inferencia_presencia import actions, backend_client, config_flow
from custom_components.inferencia_presencia.const import (
    CONF_DEV_MODE,
    CONF_INFERENCE_API_URL,
    CONF_PANEL_URL,
    CONF_SENSOR_ENTITIES,
    DOMAIN,
    SERVICE_CREATE_TEST_SENSORS,
    SERVICE_EMIT_TEST_EVENT,
    SERVICE_REFRESH_SENSOR_CATALOG,
    SERVICE_REMOVE_TEST_RESOURCES,
    SERVICE_REMOVE_TEST_SENSORS,
    SERVICE_START_FULL_REPLAY,
)
from custom_components.inferencia_presencia.services import ensure_services, remove_services
from custom_components.inferencia_presencia import catalog, event_forwarding, integration, panel, presence as presence_utils, views
from custom_components.inferencia_presencia.switch import (
    InferenciaPresenciaTestSwitch,
    async_setup_entry as setup_switches,
)
from custom_components.inferencia_presencia.coordinator import PresenceDataUpdateCoordinator
from custom_components.inferencia_presencia.sensor import async_setup_entry as setup_sensors


class FakeResponse:
    def __init__(self, status=200, body="", parsed=None, json_error=False):
        self.status = status
        self.body = body
        self.parsed = parsed
        self.json_error = json_error

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None

    async def text(self):
        return self.body

    async def json(self):
        if self.json_error:
            raise ValueError("invalid json")
        return self.parsed


class FakeSession:
    def __init__(self, *, post=None, get=None, error=None):
        self.post_response = post
        self.get_response = get
        self.error = error
        self.calls = []

    def post(self, url, **kwargs):
        self.calls.append(("post", url, kwargs))
        if self.error:
            raise self.error
        return self.post_response

    def get(self, url, **kwargs):
        self.calls.append(("get", url, kwargs))
        if self.error:
            raise self.error
        return self.get_response


def runtime(session):
    return {
        "entry_id": "entry-1",
        "backend_url": "http://backend:8081",
        "panel_base_url": "",
        "panel_token": "token",
        "dev_mode": False,
        "tracked_entities": set(),
        "auto_discovery": True,
        "http_session": session,
        "last_error": None,
        "last_scan_at": None,
        "available_entities_total": 2,
        "supported_entities_total": 1,
        "enabled_real_entities": {"binary_sensor.motion"},
        "last_real_sensor_sync_at": None,
        "recent_events": deque(maxlen=20),
        "sent_events": 0,
        "failed_events": 0,
        "last_event": None,
        "last_backend_response": None,
        "last_push_at": None,
        "coordinator": SimpleNamespace(async_apply_event_response=MagicMock()),
    }


@pytest.mark.asyncio
async def test_backend_json_clients_and_event_outcomes():
    good = runtime(FakeSession(
        post=FakeResponse(body="ok", parsed=[1, 2]),
        get=FakeResponse(body="raw", json_error=True),
    ))
    assert await backend_client.post_json(good, "/post", {"x": 1}) == {"raw": [1, 2]}
    assert await backend_client.get_json(good, "/get") == {"raw": "raw"}

    empty = runtime(FakeSession(post=FakeResponse(), get=FakeResponse()))
    assert await backend_client.post_json(empty, "/post", {}) is None
    assert await backend_client.get_json(empty, "/get") is None

    failing = runtime(FakeSession(post=FakeResponse(500, "bad"), get=FakeResponse(404, "missing")))
    with pytest.raises(RuntimeError):
        await backend_client.post_json(failing, "/post", {})
    with pytest.raises(RuntimeError):
        await backend_client.get_json(failing, "/get")

    payload = {
        "entity_id": "binary_sensor.motion",
        "state": "on",
        "sensor_type": "motion",
        "room": "kitchen",
    }
    event_runtime = runtime(FakeSession(post=FakeResponse(body='{"status":"ok"}', parsed={"status": "ok"})))
    await backend_client.forward_event(event_runtime, payload)
    assert event_runtime["sent_events"] == 1
    assert event_runtime["coordinator"].async_apply_event_response.called

    rejected = runtime(FakeSession(post=FakeResponse(503, "offline")))
    await backend_client.forward_event(rejected, payload)
    assert rejected["failed_events"] == 1

    unreachable = runtime(FakeSession(error=aiohttp.ClientConnectionError("down")))
    await backend_client.forward_event(unreachable, payload)
    assert "No fue posible" in unreachable["last_error"]


@pytest.mark.asyncio
async def test_config_and_options_flows_cover_success_and_failure(hass):
    user_input = {
        CONF_INFERENCE_API_URL: "http://backend:8081/",
        CONF_PANEL_URL: "",
        CONF_DEV_MODE: False,
        CONF_SENSOR_ENTITIES: "binary_sensor.motion",
    }
    flow = config_flow.InferenciaPresenciaConfigFlow()
    flow.hass = hass
    flow.async_set_unique_id = AsyncMock()
    flow._abort_if_unique_id_configured = MagicMock()
    flow.async_create_entry = MagicMock(side_effect=lambda **kwargs: kwargs)
    with patch.object(config_flow, "validate_backend_connection", AsyncMock()):
        result = await flow.async_step_user(user_input)
    assert result["data"][CONF_INFERENCE_API_URL] == "http://backend:8081"

    entry = MockConfigEntry(domain=DOMAIN, data=user_input, options={})
    entry.add_to_hass(hass)
    options = config_flow.InferenciaPresenciaOptionsFlow(entry)
    options.hass = hass
    options.async_show_form = MagicMock(side_effect=lambda **kwargs: kwargs)
    with patch.object(
        config_flow,
        "validate_backend_connection",
        AsyncMock(side_effect=backend_client.BackendConnectionError("down")),
    ):
        result = await options.async_step_init(user_input)
    assert result["errors"]["base"] == "cannot_connect"


@pytest.mark.asyncio
async def test_action_dispatch_and_status_publication(hass):
    domain_data = {"entries": {}}
    with (
        patch.object(actions, "refresh_catalog_for_all", AsyncMock(return_value=[{"ok": True}])),
        patch.object(actions, "create_test_sensors_for_all", AsyncMock(return_value={"created": [1]})),
        patch.object(actions, "remove_test_resources_for_all", AsyncMock(return_value={"status": "ok"})),
    ):
        assert (await actions.execute_backend_action(hass, domain_data, {"action": "refresh_catalog"}))["status"] == "ok"
        created = await actions.execute_backend_action(
            hass, domain_data, {"action": "create_test_sensors", "payload": {"include_occupancy": "yes"}}
        )
        assert created["created"] == [1]
        assert (await actions.execute_backend_action(hass, domain_data, {"action": "remove_test_resources"}))["status"] == "ok"
        assert (await actions.execute_backend_action(hass, domain_data, {"action": "unknown"}))["status"] == "error"

    current = runtime(FakeSession(post=FakeResponse(body="{}", parsed={})))
    await actions.publish_integration_status(current, poller_state="ready")
    assert current["http_session"].calls[0][0] == "post"


@pytest.mark.asyncio
async def test_services_execute_all_registered_handlers(hass):
    current = runtime(FakeSession(post=FakeResponse(body="{}", parsed={"status": "ok"})))
    domain_data = {"entries": {"entry-1": current}}
    with (
        patch("custom_components.inferencia_presencia.services.forward_event", AsyncMock()) as forward,
        patch("custom_components.inferencia_presencia.services.refresh_catalog_for_all", AsyncMock()) as refresh,
        patch("custom_components.inferencia_presencia.services.create_test_sensors_for_all", AsyncMock()) as create,
        patch("custom_components.inferencia_presencia.services.remove_test_resources_for_all", AsyncMock()) as remove,
    ):
        await ensure_services(hass, domain_data)
        await hass.services.async_call(DOMAIN, SERVICE_EMIT_TEST_EVENT, {"room": "Kitchen"}, blocking=True)
        await hass.services.async_call(DOMAIN, SERVICE_START_FULL_REPLAY, {}, blocking=True)
        await hass.services.async_call(DOMAIN, SERVICE_REFRESH_SENSOR_CATALOG, {}, blocking=True)
        await hass.services.async_call(DOMAIN, SERVICE_CREATE_TEST_SENSORS, {}, blocking=True)
        await hass.services.async_call(DOMAIN, SERVICE_REMOVE_TEST_SENSORS, {}, blocking=True)
        await hass.services.async_call(DOMAIN, SERVICE_REMOVE_TEST_RESOURCES, {}, blocking=True)
        assert forward.await_count == 1
        assert refresh.await_count == 1
        assert create.await_count == 1
        assert remove.await_count == 2
    remove_services(hass)
    assert not hass.services.has_service(DOMAIN, SERVICE_EMIT_TEST_EVENT)


@pytest.mark.asyncio
async def test_test_switch_lifecycle_and_setup(hass):
    description = {
        "entity_id": "switch.test_motion",
        "unique_id": "test-motion",
        "name": "Test motion",
    }
    hass.data[DOMAIN] = {
        "test_sensors": {
            description["entity_id"]: {**description, "state": STATE_OFF, "room": "kitchen", "sensor_type": "motion"}
        }
    }
    entity = InferenciaPresenciaTestSwitch(hass, description)
    entity.async_write_ha_state = MagicMock()
    await entity.async_added_to_hass()
    assert entity.is_on is False
    await entity.async_turn_on()
    assert entity.is_on is True
    assert entity.extra_state_attributes["room"] == "kitchen"
    await entity.async_turn_off()
    assert entity.is_on is False
    await entity.async_will_remove_from_hass()

    entry = MockConfigEntry(domain=DOMAIN)
    added = []
    await setup_switches(hass, entry, added.extend)
    assert len(added) == 1


@pytest.mark.asyncio
async def test_catalog_scan_publish_cache_and_selection(hass):
    area = __import__("homeassistant.helpers.area_registry", fromlist=["async_get"]).async_get(hass).async_create("Kitchen")
    hass.states.async_set(
        "binary_sensor.kitchen_motion", "on",
        {"friendly_name": "Kitchen motion", "device_class": "motion"},
    )
    current = runtime(FakeSession(post=FakeResponse(body="{}", parsed={})))
    current["tracked_entities"] = {"binary_sensor.kitchen_motion"}
    entities, areas = await catalog.scan_available_entities(hass, current)
    assert any(item["entity_id"] == "binary_sensor.kitchen_motion" for item in entities)
    assert any(item["area_id"] == area.id for item in areas)

    with patch.object(catalog, "post_json", AsyncMock(return_value={"status": "ok"})):
        await catalog.publish_entity_catalog(hass, current)
        await catalog.publish_entity_catalog_from_cache(current, "cached")
    assert current["available_entities_total"] >= 1
    reports = await catalog.refresh_catalog_for_all(hass, {"entries": {"entry-1": current}})
    assert reports[0]["entry_id"] == "entry-1"

    with patch.object(
        catalog, "get_json",
        AsyncMock(return_value={"enabled_entities": ["binary_sensor.kitchen_motion", "binary_sensor.unknown"]}),
    ):
        await catalog.sync_real_sensor_selection(current)
    assert current["enabled_real_entities"] == {"binary_sensor.kitchen_motion"}


class FakeRequest:
    def __init__(self, payload=None, error=False):
        self.payload = payload or {}
        self.error = error

    async def json(self):
        if self.error:
            raise ValueError("bad")
        return self.payload


@pytest.mark.asyncio
async def test_status_and_action_views(hass):
    current = runtime(FakeSession())
    current["available_entities"] = []
    current["available_areas"] = []
    current["coordinator"] = SimpleNamespace(last_update_success=True, consecutive_failures=0)
    domain_data = {"entries": {"entry-1": current}, "panel_url": "/panel"}
    response = await views.InferenciaPresenciaStatusView(domain_data).get(FakeRequest())
    assert response.status == 200
    action_view = views.InferenciaPresenciaActionsView(hass, domain_data)
    with (
        patch.object(views, "refresh_catalog_for_all", AsyncMock(return_value=[])),
        patch.object(views, "create_test_sensors_for_all", AsyncMock(return_value={"created": []})),
        patch.object(views, "remove_test_resources_for_all", AsyncMock(return_value={"status": "ok"})),
    ):
        assert (await action_view.post(FakeRequest({"action": "refresh_catalog"}))).status == 200
        assert (await action_view.post(FakeRequest({"action": "create_test_sensors"}))).status == 200
        assert (await action_view.post(FakeRequest({"action": "remove_test_resources"}))).status == 200
        assert (await action_view.post(FakeRequest({"action": "invalid"}))).status == 400
    assert (await views.InferenciaPresenciaActionsView(hass, {"entries": {}}).post(FakeRequest())).status == 409


@pytest.mark.asyncio
async def test_full_entry_setup_and_unload_lifecycle(hass):
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_INFERENCE_API_URL: "http://backend:8081", CONF_SENSOR_ENTITIES: "binary_sensor.motion"},
        entry_id="entry-coverage",
    )
    entry.add_to_hass(hass)

    class Coordinator:
        def __init__(self, _hass, fetch):
            self.fetch = fetch
            self.last_update_success = True
            self.consecutive_failures = 0

        async def async_config_entry_first_refresh(self):
            await self.fetch()

    def background(_hass, _entry, coro, _name):
        coro.close()
        return asyncio.create_task(asyncio.sleep(3600))

    hass.config_entries.async_forward_entry_setups = AsyncMock()
    hass.config_entries.async_unload_platforms = AsyncMock(return_value=True)
    with (
        patch.object(integration, "PresenceDataUpdateCoordinator", Coordinator),
        patch.object(integration, "get_json", AsyncMock(return_value={"status": "ok"})),
        patch.object(integration, "ensure_services", AsyncMock()),
        patch.object(integration, "load_test_resources", AsyncMock()),
        patch.object(integration, "assign_test_sensor_areas", AsyncMock()),
        patch.object(integration, "publish_entity_catalog", AsyncMock()),
        patch.object(integration, "sync_real_sensor_selection", AsyncMock()),
        patch.object(integration, "_create_background_task", side_effect=background),
        patch.object(integration, "_subscribe_state_events", return_value=MagicMock()),
        patch.object(integration, "_subscribe_registry_events", return_value=[]),
        patch.object(integration, "register_panel"),
        patch.object(integration, "register_status_views"),
    ):
        assert await integration.async_setup_entry(hass, entry) is True
        assert entry.runtime_data["tracked_entities"] == {"binary_sensor.motion"}
        assert await integration.async_unload_entry(hass, entry) is True


@pytest.mark.asyncio
async def test_action_poller_success_error_and_cancellation(hass):
    current = runtime(FakeSession())
    request = {"status": "claimed", "request_id": "r1", "action": "refresh_catalog"}
    with (
        patch.object(actions.asyncio, "sleep", AsyncMock(side_effect=[None, asyncio.CancelledError()])),
        patch.object(actions, "sync_real_sensor_selection", AsyncMock()),
        patch.object(actions, "publish_integration_status", AsyncMock()),
        patch.object(actions, "get_json", AsyncMock(return_value=request)),
        patch.object(actions, "execute_backend_action", AsyncMock(return_value={"status": "ok"})),
        patch.object(actions, "post_json", AsyncMock()),
    ):
        with pytest.raises(asyncio.CancelledError):
            await actions.poll_backend_actions(hass, {"entries": {}}, current)
    assert current["recent_events"][-1]["ok"] is True

    current["last_error"] = None
    with (
        patch.object(actions.asyncio, "sleep", AsyncMock(side_effect=[None, asyncio.CancelledError()])),
        patch.object(actions, "sync_real_sensor_selection", AsyncMock(side_effect=RuntimeError("down"))),
    ):
        with pytest.raises(asyncio.CancelledError):
            await actions.poll_backend_actions(hass, {"entries": {}}, current)
    assert "No fue posible" in current["last_error"]


@pytest.mark.asyncio
async def test_integration_event_subscriptions_and_panel(hass):
    current = runtime(FakeSession())
    current["enabled_real_entities"] = {"binary_sensor.motion"}
    with patch.object(integration, "process_state_change", AsyncMock()) as process:
        unsub = integration._subscribe_state_events(hass, current)
        hass.states.async_set("binary_sensor.motion", STATE_OFF)
        hass.states.async_set("binary_sensor.motion", STATE_ON)
        await hass.async_block_till_done()
        assert process.await_count >= 1
        unsub()

    domain_data = {"panel_registered": False, "panel_url": None}
    with (
        patch.object(panel, "async_register_built_in_panel") as register,
        patch.object(panel, "async_remove_panel") as remove,
    ):
        panel.register_panel(hass, domain_data, "http://backend", "", False, "token")
        assert register.called
        panel.register_panel(hass, domain_data, "http://backend", "", False, "token")
        assert register.call_count == 1
        domain_data["panel_url"] = "different"
        panel.register_panel(hass, domain_data, "http://backend", "http://other", False, "token")
        assert remove.called


@pytest.mark.asyncio
async def test_registry_refresh_setup_views_and_event_forwarding(hass):
    current = runtime(FakeSession())
    with (
        patch.object(integration.asyncio, "sleep", AsyncMock()),
        patch.object(integration, "publish_entity_catalog", AsyncMock()) as publish,
        patch.object(integration, "sync_real_sensor_selection", AsyncMock()) as sync,
    ):
        unsubs = integration._subscribe_registry_events(hass, current)
        hass.bus.async_fire("area_registry_updated", {})
        await hass.async_block_till_done()
        assert publish.await_count == 1
        assert sync.await_count == 1
        for unsub in unsubs:
            unsub()

    with (
        patch.object(integration, "register_status_views") as register_views,
        patch.object(integration, "ensure_services", AsyncMock()) as services,
    ):
        assert await integration.async_setup(hass, {}) is True
        register_views.assert_called_once()
        services.assert_awaited_once()

    state = hass.states.async_set("binary_sensor.office_motion", STATE_ON)
    current_state = hass.states.get("binary_sensor.office_motion")
    with patch.object(event_forwarding, "forward_event", AsyncMock()) as forward:
        await event_forwarding.process_state_change(current, current_state, None, "test")
        await event_forwarding.process_state_change(current, current_state, current_state, "test")
    assert forward.await_count == 1

    class Router:
        def routes(self):
            return []

    fake_hass = SimpleNamespace(
        http=SimpleNamespace(
            app=SimpleNamespace(router=Router()), register_view=MagicMock()
        )
    )
    data = {"status_view_registered": False, "entries": {}}
    views.register_status_views(fake_hass, data)
    assert data["status_view_registered"] is True
    assert fake_hass.http.register_view.call_count == 3


def test_presence_normalization_fallback_branches():
    assert presence_utils._rooms("kitchen") == []
    assert presence_utils._optional_integer("bad") is None
    assert presence_utils._integer("bad", 7) == 7
    assert presence_utils._number("bad") is None
    assert presence_utils._presence_bool("off", True) is False
    assert presence_utils._presence_bool("maybe", True) is True
    assert presence_utils.unavailable_presence_data()["service_available"] is False
    snapshot = presence_utils.normalize_snapshot(
        {"rooms": ["kitchen"], "presence": {"active_rooms": ["kitchen"]}, "model": {"ready": True}}
    )
    assert snapshot["model"] == "ai_probabilistic_presence"
    event = presence_utils.normalize_event_response(
        {
            "presencia_inferida": False,
            "habitaciones_activas": [],
            "habitacion_inferida_ia": "kitchen",
            "modelo_ia_activo": False,
        },
        snapshot,
    )
    assert event["current_room"] == presence_utils.NO_PRESENCE
    assert event["model"] == "rule_based"


@pytest.mark.asyncio
async def test_service_empty_and_replay_failure_branches(hass):
    remove_services(hass)
    domain_data = {"entries": {}}
    await ensure_services(hass, domain_data)
    await hass.services.async_call(DOMAIN, SERVICE_EMIT_TEST_EVENT, {"room": "kitchen"}, blocking=True)
    await hass.services.async_call(DOMAIN, SERVICE_START_FULL_REPLAY, {}, blocking=True)
    await hass.services.async_call(DOMAIN, SERVICE_REFRESH_SENSOR_CATALOG, {}, blocking=True)
    await hass.services.async_call(DOMAIN, SERVICE_CREATE_TEST_SENSORS, {}, blocking=True)
    remove_services(hass)

    current = runtime(FakeSession())
    domain_data = {"entries": {"entry": current}}
    with patch("custom_components.inferencia_presencia.services.post_json", AsyncMock(side_effect=RuntimeError("down"))):
        await ensure_services(hass, domain_data)
        with pytest.raises(RuntimeError):
            await hass.services.async_call(DOMAIN, SERVICE_START_FULL_REPLAY, {}, blocking=True)
    assert "No fue posible iniciar replay" in current["last_error"]


@pytest.mark.asyncio
async def test_coordinator_stale_updates_and_sensor_setup(hass):
    async def invalid():
        return None

    coordinator = PresenceDataUpdateCoordinator(hass, invalid)
    first = await coordinator._async_update_data()
    second = await coordinator._async_update_data()
    assert first["consecutive_failures"] == 1
    assert second["consecutive_failures"] == 2
    coordinator.async_apply_event_response(None)
    coordinator.async_apply_event_response({"unrecognized": True})

    entry = SimpleNamespace(entry_id="entry-1", runtime_data={"coordinator": coordinator})
    added = []
    await setup_sensors(hass, entry, added.extend)
    assert len(added) == 2
    assert added[0].native_value == presence_utils.NO_PRESENCE
    assert added[1].native_value == 0
