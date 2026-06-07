from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, INTEGRATION_VERSION
from .coordinator import PresenceDataUpdateCoordinator


class PresenceCoordinatorEntity(CoordinatorEntity):
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: PresenceDataUpdateCoordinator,
        entry: ConfigEntry,
    ) -> None:
        super().__init__(coordinator)
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name="Inferencia de presencia",
            manufacturer="Transformer Presence",
            model="Presence inference bridge",
            sw_version=INTEGRATION_VERSION,
        )

    @property
    def available(self) -> bool:
        data = self.coordinator.data or {}
        return (
            super().available
            and bool(data.get("service_available"))
            and data.get("input_mode") == "listen"
        )

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        data = self.coordinator.data or {}
        return {
            "inferencia_presencia_output": True,
            "active_rooms": list(data.get("active_rooms", [])),
            "input_mode": data.get("input_mode", "unknown"),
            "confidence": data.get("confidence"),
            "model": data.get("model", "unknown"),
            "updated_at": data.get("updated_at"),
        }
