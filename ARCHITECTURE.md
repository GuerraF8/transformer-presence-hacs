# Arquitectura de la integración

Transformer Presence Bridge separa la comunicación con Home Assistant de la
inferencia ejecutada por el backend. La integración mantiene el estado local
necesario para descubrir entidades, reenviar eventos y representar resultados,
pero no contiene el modelo ni procesa por sí sola el historial de presencia.

## Componentes

| Módulo | Responsabilidad |
| --- | --- |
| `__init__.py` | Expone el ciclo de vida requerido por Home Assistant. |
| `integration.py` | Crea el runtime, carga plataformas, registra el panel, administra suscripciones y descarga la entrada. |
| `config_flow.py` | Implementa la configuración y las opciones desde la interfaz; valida `/api/health`. |
| `runtime.py` | Define el contrato de `ConfigEntry.runtime_data`. |
| `backend_client.py` | Centraliza las solicitudes HTTP y el envío de eventos al backend. |
| `catalog.py` | Descubre áreas, dispositivos y entidades, resuelve el área efectiva y sincroniza la selección del perfil activo. |
| `event_forwarding.py` | Filtra y normaliza cambios de estado antes de enviarlos. |
| `coordinator.py` | Mantiene el snapshot normalizado de presencia y controla disponibilidad. |
| `presence.py` | Normaliza respuestas de eventos y snapshots del backend. |
| `binary_sensor.py` y `sensor.py` | Representan el resultado de la inferencia como entidades nativas. |
| `services.py` | Registra las acciones disponibles en Home Assistant. |
| `actions.py` | Consulta y ejecuta acciones solicitadas por el backend. |
| `test_sensors.py` y `switch.py` | Crean, persisten y eliminan recursos de prueba propios. |
| `views.py` | Publica endpoints HTTP autenticados de estado y acciones. |
| `panel.py` y `panel_proxy.py` | Registran el panel y adaptan HTTP/WebSocket al origen de Home Assistant. |

## Flujo de inicialización

Al cargar una entrada de configuración, la integración:

1. Construye el runtime a partir de los datos y opciones de la entrada.
2. Consulta `/api/sim_data` para obtener el estado inicial de presencia.
3. Carga las plataformas `binary_sensor`, `sensor` y `switch`.
4. Escanea las áreas y entidades y publica el catálogo en `/api/ha_entities`.
5. Consulta `/api/real_sensor_config` y cruza `enabled_entities` con el catálogo
   local.
6. Suscribe los cambios de estado y de los registros de Home Assistant.
7. Inicia la consulta periódica de acciones del backend.
8. Registra el panel lateral con acceso directo o mediante proxy.

Si la carga falla, el runtime y su token se retiran antes de propagar el error.

## Catálogo y selección de entidades

`catalog.py` recorre los estados disponibles y los combina con los registros de
entidades, dispositivos y áreas. El área asignada directamente a una entidad
tiene prioridad sobre la heredada desde su dispositivo.

El catálogo completo se publica en `/api/ha_entities`. Los eventos de los
registros de áreas, dispositivos y entidades programan una nueva publicación
con debounce para agrupar cambios consecutivos.

La selección efectiva se obtiene desde `/api/real_sensor_config`. Antes de
suscribirse lógicamente a una entidad, la integración intersecta la lista del
backend con los `entity_id` presentes en su catálogo local. Esto evita reenviar
identificadores antiguos o pertenecientes a otra instalación.

## Reenvío y actualización de presencia

La suscripción global a `state_changed` descarta:

- Entidades no habilitadas por el backend.
- Salidas creadas por la propia integración.
- Eventos sin estado nuevo.
- Transiciones que no cambian el valor.
- Estados `unknown` y `unavailable`.

Los cambios válidos se normalizan y se publican en `/api/events`. Una respuesta
válida actualiza inmediatamente el `PresenceDataUpdateCoordinator`. Como
respaldo, el coordinador consulta `/api/sim_data` cada cinco segundos.

Los dos primeros fallos consecutivos conservan el último estado conocido y
registran el contador. A partir del tercer fallo, el coordinador marca las
entidades como no disponibles.

## Acciones y recursos de prueba

`actions.py` consulta cada dos segundos `/api/ha_actions/pending`, sincroniza la
selección de entidades, publica el estado del bridge y ejecuta las acciones
admitidas:

- `refresh_catalog`
- `create_test_sensors`
- `remove_test_sensors`
- `remove_test_resources`

El resultado se devuelve al backend mediante
`/api/ha_actions/{request_id}/result`.

Los recursos de prueba se persisten con `Store`. Su eliminación se limita a los
identificadores creados por la integración y solo elimina un área cuando no
contiene recursos ajenos.

## Panel y vistas HTTP

Las vistas públicas de la integración dentro de Home Assistant requieren una
sesión autenticada:

- `GET /api/inferencia_presencia/status`
- `POST /api/inferencia_presencia/actions`
- `/api/inferencia_presencia/panel/{token}/...`

Cuando no existe una URL pública HTTPS para el panel, `panel_proxy.py` reenvía
HTTP y WebSocket al backend definido en el runtime. El token identifica la
entrada activa y el destino nunca se obtiene desde parámetros proporcionados
por el cliente.

## Contratos públicos

Los elementos que deben considerarse estables al modificar la integración son:

- Claves de configuración y opciones.
- Servicios y sus esquemas.
- Entidades, `unique_id`, estados y atributos.
- Endpoints HTTP autenticados.
- Formato del catálogo y de los eventos enviados al backend.
- Endpoints consumidos desde el backend.
- Ruta y comportamiento del panel lateral.

## Descarga

Al descargar una entrada se cancelan la actualización diferida del catálogo y
la consulta de acciones; luego se esperan ambas tareas antes de retirar las
plataformas. Si no quedan entradas, también se eliminan el panel y los servicios
compartidos.
