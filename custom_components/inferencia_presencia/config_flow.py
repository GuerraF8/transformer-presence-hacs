from __future__ import annotations

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigFlow, OptionsFlow
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult

from .const import (
    CONF_DEV_MODE,
    CONF_INFERENCE_API_URL,
    CONF_PANEL_URL,
    CONF_SENSOR_ENTITIES,
    DEFAULT_DEV_MODE,
    DEFAULT_INFERENCE_API_URL,
    DEFAULT_PANEL_URL,
    DEFAULT_SENSOR_ENTITIES,
    DOMAIN,
)


class InferenciaPresenciaConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return InferenciaPresenciaOptionsFlow(config_entry)

    async def async_step_user(
        self, user_input: dict | None = None
    ) -> FlowResult:
        if user_input is not None:
            await self.async_set_unique_id(DOMAIN)
            self._abort_if_unique_id_configured()

            backend_url = str(
                user_input.get(CONF_INFERENCE_API_URL, DEFAULT_INFERENCE_API_URL)
            ).strip()
            panel_url = str(
                user_input.get(CONF_PANEL_URL, DEFAULT_PANEL_URL)
            ).strip()
            dev_mode = bool(user_input.get(CONF_DEV_MODE, DEFAULT_DEV_MODE))
            sensor_entities = str(
                user_input.get(CONF_SENSOR_ENTITIES, DEFAULT_SENSOR_ENTITIES)
            ).strip()

            data = {
                CONF_INFERENCE_API_URL: backend_url or DEFAULT_INFERENCE_API_URL,
                CONF_PANEL_URL: panel_url,
                CONF_DEV_MODE: dev_mode,
                CONF_SENSOR_ENTITIES: sensor_entities,
            }

            return self.async_create_entry(
                title="Bridge de Inferencia de Presencia",
                data=data,
            )

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        CONF_INFERENCE_API_URL,
                        default=DEFAULT_INFERENCE_API_URL,
                    ): str,
                    vol.Optional(
                        CONF_PANEL_URL,
                        default=DEFAULT_PANEL_URL,
                    ): str,
                    vol.Optional(
                        CONF_DEV_MODE,
                        default=DEFAULT_DEV_MODE,
                    ): bool,
                    vol.Optional(
                        CONF_SENSOR_ENTITIES,
                        default=DEFAULT_SENSOR_ENTITIES,
                    ): str,
                }
            ),
        )


class InferenciaPresenciaOptionsFlow(OptionsFlow):
    def __init__(self, config_entry: ConfigEntry) -> None:
        self._config_entry = config_entry

    async def async_step_init(
        self, user_input: dict | None = None
    ) -> FlowResult:
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        current_url = self._config_entry.options.get(
            CONF_INFERENCE_API_URL,
            self._config_entry.data.get(CONF_INFERENCE_API_URL, DEFAULT_INFERENCE_API_URL),
        )
        current_panel_url = self._config_entry.options.get(
            CONF_PANEL_URL,
            self._config_entry.data.get(CONF_PANEL_URL, DEFAULT_PANEL_URL),
        )
        current_dev_mode = self._config_entry.options.get(
            CONF_DEV_MODE,
            self._config_entry.data.get(CONF_DEV_MODE, DEFAULT_DEV_MODE),
        )
        current_entities = self._config_entry.options.get(
            CONF_SENSOR_ENTITIES,
            self._config_entry.data.get(CONF_SENSOR_ENTITIES, DEFAULT_SENSOR_ENTITIES),
        )

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Optional(CONF_INFERENCE_API_URL, default=current_url): str,
                    vol.Optional(CONF_PANEL_URL, default=current_panel_url): str,
                    vol.Optional(CONF_DEV_MODE, default=current_dev_mode): bool,
                    vol.Optional(CONF_SENSOR_ENTITIES, default=current_entities): str,
                }
            ),
        )
