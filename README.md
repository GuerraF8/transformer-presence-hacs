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

- `URL base del backend`: URL HTTP/HTTPS del backend, sin ruta final. Ejemplo: `http://192.168.1.50:8081`.
- `Entidades a escuchar`: lista opcional separada por comas. Si queda vacia, la integracion escucha automaticamente dominios comunes como `binary_sensor`, `sensor`, `person`, `device_tracker`, `input_boolean`, `switch`, `cover` y `lock`.

La URL del backend se guarda en la entrada de configuracion de Home Assistant y puede cambiarse desde las opciones de la integracion. No se usa `backend_url.override` ni scripts SSH para configurar una instalacion HACS.

## Servicios

La integracion registra estos servicios:

- `inferencia_presencia.emitir_evento_prueba`
- `inferencia_presencia.iniciar_replay_historico`
- `inferencia_presencia.refrescar_catalogo_sensores`
- `inferencia_presencia.crear_sensores_prueba`

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
