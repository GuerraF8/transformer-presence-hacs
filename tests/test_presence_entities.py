from __future__ import annotations

from collections.abc import Callable

import pytest
from homeassistant.helpers.update_coordinator import UpdateFailed

from custom_components.inferencia_presencia.binary_sensor import (
    HomePresenceBinarySensor,
    RoomOccupancyBinarySensor,
    async_setup_entry as async_setup_binary_sensors,
)
from custom_components.inferencia_presencia.coordinator import (
    PresenceDataUpdateCoordinator,
)
from custom_components.inferencia_presencia.presence import normalize_snapshot
from custom_components.inferencia_presencia.sensor import (
    CurrentRoomSensor,
    EstimatedPeopleSensor,
)

from .test_presence_normalization import snapshot


class FakeConfigEntry:
    entry_id = "entry-1"

    def __init__(self, runtime_data: dict) -> None:
        self.runtime_data = runtime_data
        self.unload_callbacks: list[Callable] = []

    def async_on_unload(self, callback: Callable) -> None:
        self.unload_callbacks.append(callback)


async def test_entity_states_and_mode_availability(hass) -> None:
    async def fetch_snapshot() -> dict:
        return snapshot(active_rooms=["kitchen"])

    coordinator = PresenceDataUpdateCoordinator(hass, fetch_snapshot)
    coordinator.async_set_updated_data(
        normalize_snapshot(snapshot(active_rooms=["kitchen"]))
    )
    entry = FakeConfigEntry({"coordinator": coordinator})

    home = HomePresenceBinarySensor(coordinator, entry)
    kitchen = RoomOccupancyBinarySensor(coordinator, entry, "kitchen")
    current_room = CurrentRoomSensor(coordinator, entry)
    people = EstimatedPeopleSensor(coordinator, entry)

    assert home.is_on is True
    assert kitchen.is_on is True
    assert current_room.native_value == "kitchen"
    assert people.native_value == 1
    assert home.available is True

    coordinator.async_set_updated_data(
        normalize_snapshot(snapshot(active_rooms=["kitchen"], input_mode="replay"))
    )

    assert home.available is False
    assert kitchen.available is False


async def test_dynamic_rooms_and_removed_room_availability(hass) -> None:
    async def fetch_snapshot() -> dict:
        return snapshot(active_rooms=[])

    coordinator = PresenceDataUpdateCoordinator(hass, fetch_snapshot)
    coordinator.async_set_updated_data(normalize_snapshot(snapshot(active_rooms=[])))
    entry = FakeConfigEntry({"coordinator": coordinator})
    added = []

    await async_setup_binary_sensors(hass, entry, added.extend)
    coordinator.async_set_updated_data(
        normalize_snapshot(
            snapshot(
                rooms=["bedroom", "kitchen", "office"],
                active_rooms=["office"],
            )
        )
    )

    office = next(
        entity
        for entity in added
        if isinstance(entity, RoomOccupancyBinarySensor)
        and entity._room == "office"
    )
    assert office.is_on is True
    assert office.available is True

    coordinator.async_set_updated_data(
        normalize_snapshot(
            snapshot(rooms=["bedroom", "kitchen"], active_rooms=[])
        )
    )
    assert office.available is False


async def test_three_failures_then_recovery(hass) -> None:
    responses: list[dict | Exception] = [
        snapshot(active_rooms=["kitchen"]),
        OSError("offline-1"),
        OSError("offline-2"),
        OSError("offline-3"),
        snapshot(active_rooms=[]),
    ]

    async def fetch_snapshot() -> dict:
        response = responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response

    coordinator = PresenceDataUpdateCoordinator(hass, fetch_snapshot)
    coordinator.async_set_updated_data(await coordinator._async_update_data())

    assert (await coordinator._async_update_data())["active_rooms"] == ["kitchen"]
    assert (await coordinator._async_update_data())["active_rooms"] == ["kitchen"]
    with pytest.raises(UpdateFailed):
        await coordinator._async_update_data()

    recovered = await coordinator._async_update_data()
    assert recovered["active_rooms"] == []
    assert coordinator.consecutive_failures == 0
