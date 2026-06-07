from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import timedelta
import logging
from typing import Any

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import DOMAIN
from .presence import (
    normalize_event_response,
    normalize_snapshot,
    unavailable_presence_data,
)

LOGGER = logging.getLogger(__name__)
POLL_INTERVAL = timedelta(seconds=5)
FAILURES_BEFORE_UNAVAILABLE = 3


class PresenceDataUpdateCoordinator(DataUpdateCoordinator):
    def __init__(
        self,
        hass: HomeAssistant,
        fetch_snapshot: Callable[[], Awaitable[dict[str, Any] | None]],
    ) -> None:
        super().__init__(
            hass,
            LOGGER,
            name=f"{DOMAIN}_presence",
            update_interval=POLL_INTERVAL,
        )
        self._fetch_snapshot = fetch_snapshot
        self.consecutive_failures = 0

    async def _async_update_data(self) -> dict[str, Any]:
        try:
            payload = await self._fetch_snapshot()
            if not isinstance(payload, dict):
                raise RuntimeError("El backend no devolvio un snapshot JSON valido")
        except Exception as err:
            self.consecutive_failures += 1
            if self.consecutive_failures >= FAILURES_BEFORE_UNAVAILABLE:
                raise UpdateFailed(
                    f"Backend de inferencia no disponible tras "
                    f"{self.consecutive_failures} intentos: {err}"
                ) from err

            stale = dict(self.data or unavailable_presence_data())
            stale["consecutive_failures"] = self.consecutive_failures
            return stale

        self.consecutive_failures = 0
        return normalize_snapshot(payload)

    @callback
    def async_apply_event_response(self, payload: dict[str, Any] | None) -> None:
        if not isinstance(payload, dict):
            return
        normalized = normalize_event_response(payload, self.data)
        if normalized is None:
            return
        self.consecutive_failures = 0
        self.async_set_updated_data(normalized)
