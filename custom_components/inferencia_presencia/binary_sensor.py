from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback

from .coordinator import PresenceDataUpdateCoordinator
from .entity import PresenceCoordinatorEntity
from .presence import room_slug


class HomePresenceBinarySensor(PresenceCoordinatorEntity, BinarySensorEntity):
    _attr_device_class = BinarySensorDeviceClass.OCCUPANCY
    _attr_translation_key = "home_presence"
    _attr_suggested_object_id = "inferencia_presencia_hogar"

    def __init__(
        self,
        coordinator: PresenceDataUpdateCoordinator,
        entry: ConfigEntry,
    ) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_home_presence"

    @property
    def is_on(self) -> bool:
        return bool((self.coordinator.data or {}).get("active_rooms"))


class RoomOccupancyBinarySensor(PresenceCoordinatorEntity, BinarySensorEntity):
    _attr_device_class = BinarySensorDeviceClass.OCCUPANCY
    _attr_translation_key = "room_occupancy"

    def __init__(
        self,
        coordinator: PresenceDataUpdateCoordinator,
        entry: ConfigEntry,
        room: str,
    ) -> None:
        super().__init__(coordinator, entry)
        self._room = room
        slug = room_slug(room)
        self._attr_unique_id = f"{entry.entry_id}_room_{slug}"
        self._attr_suggested_object_id = f"inferencia_presencia_{slug}"
        self._attr_translation_placeholders = {"room": room}

    @property
    def available(self) -> bool:
        return (
            super().available
            and self._room in (self.coordinator.data or {}).get("rooms", [])
        )

    @property
    def is_on(self) -> bool:
        return self._room in (self.coordinator.data or {}).get("active_rooms", [])


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities,
) -> None:
    runtime = entry.runtime_data
    coordinator: PresenceDataUpdateCoordinator = runtime["coordinator"]
    added_rooms: set[str] = set()

    @callback
    def add_new_rooms() -> None:
        rooms = set((coordinator.data or {}).get("rooms", []))
        new_rooms = sorted(rooms - added_rooms)
        if not new_rooms:
            return
        added_rooms.update(new_rooms)
        async_add_entities(
            [
                RoomOccupancyBinarySensor(coordinator, entry, room)
                for room in new_rooms
            ]
        )

    async_add_entities([HomePresenceBinarySensor(coordinator, entry)])
    add_new_rooms()
    entry.async_on_unload(coordinator.async_add_listener(add_new_rooms))
