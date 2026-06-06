# Transformer Presence Bridge para Home Assistant

Integracion custom de Home Assistant para conectar sensores y eventos de estado con el backend externo de Transformer Presence.

La integracion registra un panel en la barra lateral, publica el catalogo de entidades disponibles al backend, escucha cambios de estado y reenvia eventos normalizados para inferencia de presencia.

## Requisitos

- Home Assistant con HACS instalado.
- Backend Transformer Presence ejecutandose en Docker.
- Una URL del backend alcanzable desde Home Assistant y desde el navegador donde se abre el panel.

Ejemplo de URL:

```text
http://192.168.1.50:8081
```

Si usas Tailscale, usa la IP o nombre Tailscale del equipo que ejecuta Docker. Evita `127.0.0.1` salvo que Home Assistant, el navegador y el backend esten realmente en el mismo host y red.

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
- `URL publica del panel para el navegador`: opcional. Usala cuando abres Home Assistant remotamente y el navegador necesita otra ruta hacia el backend. Ejemplo: `http://100.68.121.126:8081`.
- `Modo desarrollador`: desactivado por defecto. Al activarlo, el panel muestra las herramientas de Replay y el acceso al Simulador.
- `Entidades a escuchar`: lista opcional separada por comas. Si queda vacia, la integracion escucha automaticamente dominios comunes como `binary_sensor`, `sensor`, `person`, `device_tracker`, `input_boolean`, `switch`, `cover` y `lock`.

La URL interna se usa para publicar eventos, catalogo y heartbeat desde Home Assistant hacia el backend. La URL publica se usa solo para registrar el panel iframe en la barra lateral. Si dejas la URL publica vacia, el panel usa la URL interna.

El panel registrado agrega los parametros `embedded=1` y `dev=0|1` sin eliminar parametros existentes de la URL publica. Abrir el backend directamente mantiene visibles las herramientas de desarrollo.

La configuracion se guarda en la entrada de Home Assistant y puede cambiarse desde las opciones de la integracion. No se usa `backend_url.override` ni scripts SSH para configurar una instalacion HACS.

Ejemplo con Home Assistant en LAN y acceso remoto por Tailscale:

```text
URL interna del backend para Home Assistant: http://192.168.0.221:8081
URL publica del panel para el navegador:     http://100.68.121.126:8081
```

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
