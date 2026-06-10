from __future__ import annotations

DOMAIN = "inferencia_presencia"
INTEGRATION_VERSION = "1.2.1"

CONF_INFERENCE_API_URL = "inference_api_url"
DEFAULT_INFERENCE_API_URL = "http://127.0.0.1:8081"

CONF_PANEL_URL = "panel_url"
DEFAULT_PANEL_URL = ""

CONF_DEV_MODE = "dev_mode"
DEFAULT_DEV_MODE = False

CONF_SENSOR_ENTITIES = "sensor_entities"
DEFAULT_SENSOR_ENTITIES = ""

PANEL_TITLE = "Inferencia Presencia"
PANEL_ICON = "mdi:graph-outline"
PANEL_URL_PATH = "inferencia-presencia"

SERVICE_EMIT_TEST_EVENT = "emitir_evento_prueba"
SERVICE_START_FULL_REPLAY = "iniciar_replay_historico"
SERVICE_REFRESH_SENSOR_CATALOG = "refrescar_catalogo_sensores"
SERVICE_CREATE_TEST_SENSORS = "crear_sensores_prueba"

MAX_RECENT_EVENTS = 120
MAX_ENTITY_CATALOG = 500
