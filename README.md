# Transformer Presence Bridge para Home Assistant

Integracion custom de Home Assistant para conectar sensores y eventos de estado con el backend externo de Transformer Presence.

La integracion registra un panel en la barra lateral, publica el catalogo de entidades disponibles al backend, escucha cambios de estado y reenvia eventos normalizados para inferencia de presencia.

La version `1.3.0` incorpora un proxy HTTP/WebSocket para publicar el panel por
el mismo origen que Home Assistant. Consulta [ARCHITECTURE.md](ARCHITECTURE.md).

## Requisitos

- Home Assistant 2026.1.0 o posterior con HACS instalado.
- Backend Transformer Presence ejecutandose en Docker.
- Una URL del backend alcanzable desde Home Assistant Core.

Ejemplo de URL:

```text
http://192.168.1.50:8081
```

Si usas Tailscale, usa la IP o nombre Tailscale del equipo que ejecuta Docker.
Evita `127.0.0.1` salvo que Home Assistant Core y el backend esten en el mismo
host o contenedor de red.

## Instalacion con HACS

1. En Home Assistant, abre HACS.
2. Ve a `Integrations`.
3. Abre el menu de repositorios personalizados.
4. Agrega este repositorio como tipo `Integration`:

```text
https://github.com/GuerraF8/transformer-presence-hacs
```

5. Descarga `Transformer Presence Bridge`.
6. Reinicia Home Assistant.
7. Ve a `Settings > Devices & services > Add integration`.
8. Busca `Transformer Presence Bridge`.
9. Ingresa la URL base del backend.

## Configuracion

Campos disponibles:

- `URL interna del backend para Home Assistant`: URL HTTP/HTTPS que Home Assistant Core puede alcanzar. Ejemplo: `http://192.168.1.50:8081`.
- `URL publica HTTPS del panel`: opcional. Solo se usa como acceso directo cuando comienza con `https://`.
- `Modo desarrollador`: desactivado por defecto. Al activarlo, el panel muestra las herramientas de Replay y el acceso al Simulador.
- `Entidades a escuchar`: lista opcional separada por comas. Si queda vacia, la integracion escucha automaticamente dominios comunes como `binary_sensor`, `sensor`, `person`, `device_tracker`, `input_boolean`, `switch`, `cover` y `lock`.

La URL interna se usa para publicar eventos, catalogo y heartbeat. Si la URL
publica queda vacia o usa HTTP, Home Assistant publica el panel mediante un
proxy relativo con token. Esto evita contenido mixto cuando la interfaz se abre
por HTTPS mediante Home Assistant Cloud o Nabu Casa. Una URL publica HTTPS se
mantiene como acceso directo.

El panel registrado agrega los parametros `embedded=1` y `dev=0|1` sin eliminar
parametros existentes. El proxy reenvia REST y WebSocket al backend configurado,
sin aceptar destinos proporcionados por el navegador.

La configuracion se guarda en la entrada de Home Assistant y puede cambiarse desde las opciones de la integracion.

Ejemplo con Home Assistant en LAN y acceso remoto por Nabu Casa:

```text
URL interna del backend para Home Assistant: http://192.168.0.221:8081
URL publica HTTPS del panel:                 (vacia)
```

## Entidades para automatizaciones

Desde la version `1.2.0`, la integracion crea entidades nativas agrupadas bajo el dispositivo `Inferencia de presencia`:

- `binary_sensor.inferencia_presencia_hogar`: activo si existe al menos una habitacion ocupada.
- `binary_sensor.inferencia_presencia_<habitacion>`: ocupacion inferida para cada habitacion del mapa.
- `sensor.inferencia_presencia_habitacion_actual`: habitacion inferida o `sin_presencia`.
- `sensor.inferencia_presencia_personas_estimadas`: cantidad actual estimada.

Las entidades se actualizan inmediatamente con la respuesta de `/api/events` y consultan `/api/sim_data` cada 5 segundos como respaldo. Solo estan disponibles en modo de sensores reales (`listen`). Replay, Simulador o tres fallos consecutivos del backend las marcan como `unavailable`, sin publicar una falsa ausencia.

Home Assistant puede agregar un sufijo al `entity_id` si ya existe otra entidad con el mismo nombre. Usa el ID mostrado en `Settings > Devices & services > Entities` al crear la automatizacion.

Ejemplo de automatizacion que enciende una luz al detectar ocupacion en cocina:

```yaml
alias: Encender cocina por presencia inferida
trigger:
  - platform: state
    entity_id: binary_sensor.inferencia_presencia_kitchen
    from: "off"
    to: "on"
condition:
  - condition: state
    entity_id: binary_sensor.inferencia_presencia_hogar
    state: "on"
action:
  - service: light.turn_on
    target:
      entity_id: light.cocina
mode: single
```

Ejemplo de condicion reutilizable:

```yaml
condition:
  - condition: state
    entity_id: sensor.inferencia_presencia_habitacion_actual
    state: "kitchen"
  - condition: numeric_state
    entity_id: sensor.inferencia_presencia_personas_estimadas
    above: 0
```

El historial de estas entidades queda disponible mediante Recorder cuando ese componente estandar de Home Assistant esta habilitado.

## Servicios

La integracion registra estos servicios:

- `inferencia_presencia.emitir_evento_prueba`
- `inferencia_presencia.iniciar_replay_historico`
- `inferencia_presencia.refrescar_catalogo_sensores`
- `inferencia_presencia.crear_sensores_prueba`

## Seguridad y entidades reales

La integracion separa el catalogo de entidades del envio de eventos:

- Puede publicar al backend un catalogo amplio para que el usuario seleccione sensores.
- Solo envia cambios de estado de entidades que el backend ya marco como `enabled_entities`.
- Antes de enviar, cruza esa lista con el catalogo local de esta instancia de Home Assistant para evitar entradas antiguas o de otra maquina.
- Los sensores de prueba se crean como `switch.inferencia_*_test` con `unique_id` propio.
- La integracion no modifica entidades existentes de otros dominios ni requiere cambios en `configuration.yaml`.

Esto evita que una instalacion con sensores reales llamados igual que los sensores del historico CSV empiece a alimentar inferencia sin confirmacion explicita en el panel del backend.

## Diagnostico

La integracion expone:

```text
GET /api/inferencia_presencia/status
```

Ese endpoint muestra la URL activa del backend, errores recientes, eventos enviados y el ultimo catalogo de entidades detectadas.

## Backend

El backend se despliega aparte desde:

```text
https://github.com/GuerraF8/transformer-presence-backend
```

El flujo recomendado para clientes es instalar esta integracion con HACS y levantar el backend con `docker-compose.yml` mas `.env`.
