# Arquitectura de la integración

`__init__.py` solo exporta el ciclo de vida requerido por Home Assistant.
`integration.py` coordina la configuración, recarga, suscripciones y descarga.
`runtime.py` define el contrato de `ConfigEntry.runtime_data`;
`backend_client.py` contiene el transporte HTTP; `catalog.py` descubre áreas,
dispositivos y entidades, resuelve el área efectiva y sincroniza el catálogo;
`actions.py` ejecuta solicitudes del backend;
`event_forwarding.py` normaliza cambios de estado; `services.py` registra los
servicios; `views.py` contiene las vistas HTTP; `test_sensors.py` administra
áreas y sensores de prueba propios, `panel.py` administra el iframe y
`panel_proxy.py` publica
HTTP y WebSocket mediante el mismo origen de Home Assistant.

Las plataformas `binary_sensor`, `sensor` y `switch` permanecen independientes.
El `PresenceDataUpdateCoordinator` conserva el estado normalizado y notifica a
las entidades. Al descargar una entrada se cancelan y esperan las tareas de
consulta periódica antes de retirar plataformas, servicios y panel.

Los contratos públicos de la integración incluyen sus servicios, entidades,
opciones de configuración, vistas HTTP y URL del panel.

Los eventos de los registros de áreas, dispositivos y entidades reconstruyen
el catálogo con debounce. El reenvío de estados consulta exclusivamente
`enabled_real_entities`, sincronizado desde el perfil activo del backend. Los
IDs de recursos de prueba se guardan en `Store`; su limpieza comprueba que un
área no contenga entidades o dispositivos ajenos antes de eliminarla.
