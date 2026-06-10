from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.frontend import (
    async_register_built_in_panel,
    async_remove_panel,
)
from homeassistant.core import HomeAssistant

from .const import PANEL_ICON, PANEL_TITLE, PANEL_URL_PATH
from .ha_utils import resolve_panel_url

LOGGER = logging.getLogger(__name__)


def register_panel(
    hass: HomeAssistant,
    domain_data: dict[str, Any],
    backend_url: str,
    panel_base_url: str,
    dev_mode: bool,
) -> None:
    panel_url = resolve_panel_url(panel_base_url, backend_url, dev_mode)
    if domain_data.get("panel_registered") and domain_data.get("panel_url") == panel_url:
        return
    try:
        if domain_data.get("panel_registered"):
            async_remove_panel(hass, PANEL_URL_PATH)
        async_register_built_in_panel(
            hass,
            component_name="iframe",
            frontend_url_path=PANEL_URL_PATH,
            config={"url": panel_url},
            sidebar_title=PANEL_TITLE,
            sidebar_icon=PANEL_ICON,
            require_admin=False,
        )
    except Exception as err:  # noqa: BLE001
        LOGGER.error("No se pudo registrar panel: %s", err)
        return
    domain_data["panel_registered"] = True
    domain_data["panel_url"] = panel_url
