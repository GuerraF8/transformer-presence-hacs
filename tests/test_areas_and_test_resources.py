from __future__ import annotations

from types import SimpleNamespace

from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import entity_registry as er
import pytest

from custom_components.inferencia_presencia.catalog import resolve_effective_area
from custom_components.inferencia_presencia.test_sensors import (
    create_test_sensors_for_all,
    load_test_resources,
    remove_test_resources_for_all,
)


class FakeDeviceRegistry:
    def __init__(self, devices: dict[str, object]) -> None:
        self.devices = devices

    def async_get(self, device_id: str):
        return self.devices.get(device_id)


def test_entity_area_takes_priority_over_device_area() -> None:
    registry = FakeDeviceRegistry(
        {"device-1": SimpleNamespace(area_id="area-device")}
    )
    entry = SimpleNamespace(area_id="area-entity", device_id="device-1")
    assert resolve_effective_area(entry, registry) == (
        "area-entity",
        "entity",
        "device-1",
    )


def test_device_area_is_inherited_when_entity_has_no_area() -> None:
    registry = FakeDeviceRegistry(
        {"device-1": SimpleNamespace(area_id="area-device")}
    )
    entry = SimpleNamespace(area_id=None, device_id="device-1")
    assert resolve_effective_area(entry, registry) == (
        "area-device",
        "device",
        "device-1",
    )


@pytest.mark.asyncio
async def test_test_resource_cleanup_preserves_area_with_foreign_entity(
    hass,
) -> None:
    domain_data = {
        "entries": {},
        "test_switch_adders": {},
        "test_switch_entities": {},
    }
    await load_test_resources(hass, domain_data)
    created = await create_test_sensors_for_all(
        hass,
        domain_data,
        rooms_raw="kitchen,living",
        include_occupancy=True,
        initial_state="off",
    )

    resources = domain_data["test_resources"]
    assert len(resources["areas"]) == 2
    assert len(resources["sensors"]) == 6
    assert len(created["created_areas"]) == 2
    assert len(created["created_sensors"]) == 6
    area_id = next(iter(resources["areas"]))
    area = ar.async_get(hass).async_get_area(area_id)
    assert area is not None
    assert area.name.startswith("Inferencia prueba ·")

    registry = er.async_get(hass)
    foreign = registry.async_get_or_create(
        "sensor",
        "foreign_platform",
        "foreign_unique",
        suggested_object_id="foreign_sensor",
    )
    registry.async_update_entity(foreign.entity_id, area_id=area_id)

    result = await remove_test_resources_for_all(
        hass,
        domain_data,
        include_areas=True,
    )
    assert len(result["removed_sensors"]) == 6
    assert area_id in result["preserved_areas"]
    assert ar.async_get(hass).async_get_area(area_id) is not None
    assert len(result["removed_areas"]) == 1
