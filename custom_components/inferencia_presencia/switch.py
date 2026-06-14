from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback

from .const import DOMAIN


class InferenciaPresenciaTestSwitch(SwitchEntity):
    _attr_should_poll = False
    _attr_has_entity_name = False

    def __init__(self, hass: HomeAssistant, description: dict[str, Any]) -> None:
        self._hass = hass
        self._entity_id = str(description["entity_id"])
        self._attr_entity_id = self._entity_id
        self._attr_unique_id = str(description["unique_id"])
        self._attr_name = str(description["name"])

    async def async_added_to_hass(self) -> None:
        domain_data = self._hass.data.setdefault(DOMAIN, {})
        entities = domain_data.setdefault("test_switch_entities", {})
        entities[self._entity_id] = self

    async def async_will_remove_from_hass(self) -> None:
        domain_data = self._hass.data.get(DOMAIN, {})
        entities = domain_data.get("test_switch_entities", {})
        if isinstance(entities, dict):
            entities.pop(self._entity_id, None)

    @property
    def _store_item(self) -> dict[str, Any]:
        domain_data = self._hass.data.get(DOMAIN, {})
        store = domain_data.get("test_sensors", {}) if isinstance(domain_data, dict) else {}
        item = store.get(self._entity_id) if isinstance(store, dict) else None
        return item if isinstance(item, dict) else {}

    @property
    def is_on(self) -> bool:
        return str(self._store_item.get("state") or "off").lower() == "on"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        item = self._store_item
        return {
            "inferencia_presencia_test": True,
            "room": item.get("room", ""),
            "sensor_type": item.get("sensor_type", "other"),
            "area_id": item.get("area_id", ""),
        }

    async def async_turn_on(self, **kwargs: Any) -> None:
        self._set_state("on")

    async def async_turn_off(self, **kwargs: Any) -> None:
        self._set_state("off")

    def _set_state(self, state: str) -> None:
        item = self._store_item
        if item:
            item["state"] = state
        self.async_write_ha_state()


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities,
) -> None:
    domain_data = hass.data.setdefault(DOMAIN, {})
    store = domain_data.setdefault("test_sensors", {})
    adders = domain_data.setdefault("test_switch_adders", {})

    @callback
    def add_test_switches(items: list[dict[str, Any]]) -> None:
        async_add_entities([InferenciaPresenciaTestSwitch(hass, item) for item in items])

    adders[entry.entry_id] = add_test_switches
    entry.async_on_unload(lambda: adders.pop(entry.entry_id, None))

    if isinstance(store, dict) and store:
        add_test_switches([item.copy() for item in store.values() if isinstance(item, dict)])
