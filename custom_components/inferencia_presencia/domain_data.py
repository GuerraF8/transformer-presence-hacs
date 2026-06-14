"""Estado compartido por los componentes de la integración."""

from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant

from .const import DOMAIN

DOMAIN_DEFAULTS: dict[str, Any] = {
    "entries": {},
    "services_registered": False,
    "panel_registered": False,
    "panel_url": None,
    "panel_tokens": {},
    "status_view_registered": False,
    "test_sensors": {},
    "test_switch_adders": {},
}


def ensure_domain_data(hass: HomeAssistant) -> dict[str, Any]:
    existing = hass.data.get(DOMAIN)
    if isinstance(existing, dict):
        for key, value in DOMAIN_DEFAULTS.items():
            existing.setdefault(key, value if not isinstance(value, dict) else {})
        return existing

    hass.data[DOMAIN] = {
        key: value if not isinstance(value, dict) else {}
        for key, value in DOMAIN_DEFAULTS.items()
    }
    return hass.data[DOMAIN]
