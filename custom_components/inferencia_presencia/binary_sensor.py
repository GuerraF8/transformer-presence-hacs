from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback

from .coordinator import PresenceDataUpdateCoordinator
from .entity import PresenceCoordinatorEntity
from .presence import room_display_name, room_slug


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

    @property
    def room_name(self) -> str:
        labels = (self.coordinator.data or {}).get("room_labels", {})
        if isinstance(labels, dict):
            label = str(labels.get(self._room) or "").strip()
            if label:
                return label
        return room_display_name(self._room)

    @property
    def name(self) -> str:
        return f"Ocupación en {self.room_name}"

    @property
    def extra_state_attributes(self) -> dict[str, object]:
        attributes = dict(super().extra_state_attributes)
        data = self.coordinator.data or {}
        attributes.update(
            {
                "room_slug": self._room,
                "room_name": self.room_name,
                "layout_version": data.get("layout_version"),
                "layout_source": data.get("layout_source", "unknown"),
            }
        )
        return attributes

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
    entities_by_room: dict[str, RoomOccupancyBinarySensor] = {}

    @callback
    def add_new_rooms() -> None:
        rooms = set((coordinator.data or {}).get("rooms", []))
        new_rooms = sorted(rooms - entities_by_room.keys())
        if not new_rooms:
            return
        new_entities = [
            RoomOccupancyBinarySensor(coordinator, entry, room)
            for room in new_rooms
        ]
        entities_by_room.update(
            {entity._room: entity for entity in new_entities}
        )
        async_add_entities(new_entities)

    async_add_entities([HomePresenceBinarySensor(coordinator, entry)])
    add_new_rooms()
    entry.async_on_unload(coordinator.async_add_listener(add_new_rooms))
