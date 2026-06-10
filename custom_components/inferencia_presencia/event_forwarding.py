"""Normalización y envío de cambios de estado al backend."""

from __future__ import annotations

from homeassistant.core import State

from .backend_client import forward_event
from .ha_utils import infer_room, infer_sensor_type
from .runtime import IntegrationRuntime


async def process_state_change(
    runtime: IntegrationRuntime,
    new_state: State,
    old_state: State | None,
    source: str,
) -> None:
    if old_state is not None and old_state.state == new_state.state:
        return
    if new_state.state.lower() in {"unknown", "unavailable"}:
        return
    attrs = new_state.attributes or {}
    await forward_event(
        runtime,
        {
            "entity_id": new_state.entity_id,
            "state": new_state.state,
            "sensor_type": str(
                attrs.get("sensor_type") or infer_sensor_type(new_state.entity_id)
            ).strip().lower(),
            "room": str(
                attrs.get("room") or infer_room(new_state.entity_id)
            ).strip().lower(),
            "timestamp": new_state.last_changed.isoformat(),
            "source": source,
        },
    )
