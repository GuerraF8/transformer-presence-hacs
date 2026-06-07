from __future__ import annotations

from homeassistant.components.sensor import SensorEntity, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .coordinator import PresenceDataUpdateCoordinator
from .entity import PresenceCoordinatorEntity
from .presence import NO_PRESENCE


class CurrentRoomSensor(PresenceCoordinatorEntity, SensorEntity):
    _attr_translation_key = "current_room"
    _attr_suggested_object_id = "inferencia_presencia_habitacion_actual"

    def __init__(
        self,
        coordinator: PresenceDataUpdateCoordinator,
        entry: ConfigEntry,
    ) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_current_room"

    @property
    def native_value(self) -> str:
        data = self.coordinator.data or {}
        if not data.get("active_rooms"):
            return NO_PRESENCE
        return str(data.get("current_room") or NO_PRESENCE)


class EstimatedPeopleSensor(PresenceCoordinatorEntity, SensorEntity):
    _attr_translation_key = "estimated_people"
    _attr_suggested_object_id = "inferencia_presencia_personas_estimadas"
    _attr_native_unit_of_measurement = "people"
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(
        self,
        coordinator: PresenceDataUpdateCoordinator,
        entry: ConfigEntry,
    ) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_estimated_people"

    @property
    def native_value(self) -> int:
        return int((self.coordinator.data or {}).get("people_estimate", 0))


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities,
) -> None:
    runtime = entry.runtime_data
    coordinator: PresenceDataUpdateCoordinator = runtime["coordinator"]
    async_add_entities(
        [
            CurrentRoomSensor(coordinator, entry),
            EstimatedPeopleSensor(coordinator, entry),
        ]
    )
