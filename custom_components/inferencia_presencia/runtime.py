from __future__ import annotations

from collections import deque
from typing import Any, NotRequired, TypedDict

import aiohttp

from homeassistant.helpers.update_coordinator import DataUpdateCoordinator


class IntegrationRuntime(TypedDict):
    entry_id: str
    backend_url: str
    panel_base_url: str
    panel_token: str
    dev_mode: bool
    tracked_entities: set[str]
    auto_discovery: bool
    http_session: aiohttp.ClientSession
    unsub: Any
    action_poll_task: Any
    last_event: dict[str, Any] | None
    last_backend_response: dict[str, Any] | None
    last_error: str | None
    last_push_at: str | None
    last_scan_at: str | None
    available_entities: list[dict[str, Any]]
    available_areas: list[dict[str, Any]]
    available_entities_total: int
    supported_entities_total: int
    enabled_real_entities: set[str]
    last_real_sensor_sync_at: str | None
    recent_events: deque[dict[str, Any]]
    sent_events: int
    failed_events: int
    coordinator: NotRequired[DataUpdateCoordinator]
    registry_unsubs: list[Any]
    catalog_refresh_task: Any
