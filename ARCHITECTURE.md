# Arquitectura de la integración

`__init__.py` solo exporta el ciclo de vida requerido por Home Assistant.
`integration.py` coordina la configuración, recarga, suscripciones y descarga.
`runtime.py` define el contrato de `ConfigEntry.runtime_data`;
`backend_client.py` contiene el transporte HTTP; `catalog.py` descubre y
sincroniza entidades; `actions.py` ejecuta solicitudes del backend;
`event_forwarding.py` normaliza cambios de estado; `services.py` registra los
servicios; `views.py` contiene las vistas HTTP; `test_sensors.py` administra
sensores de prueba y `panel.py` administra el iframe.

Las plataformas `binary_sensor`, `sensor` y `switch` permanecen independientes.
El `PresenceDataUpdateCoordinator` conserva el estado normalizado y notifica a
las entidades. Al descargar una entrada se cancelan y esperan las tareas de
consulta periódica antes de retirar plataformas, servicios y panel.

Los contratos públicos de la integración incluyen sus servicios, entidades,
opciones de configuración, vistas HTTP y URL del panel.
