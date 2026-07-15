# Transformer Presence Bridge para Home Assistant

Integración personalizada de Home Assistant que conecta las entidades de una
instalación con el backend de Transformer Presence.

La integración funciona como un puente bidireccional: descubre áreas y
entidades, publica ese catálogo al backend, reenvía cambios de estado de las
entidades habilitadas y representa el resultado de la inferencia mediante
entidades nativas de Home Assistant. El modelo, los perfiles, el historial y
la lógica de inferencia permanecen en el backend.

Consulta [ARCHITECTURE.md](ARCHITECTURE.md) para conocer los componentes y
contratos internos.

## Funcionalidades

- Configuración completa desde la interfaz de Home Assistant, sin modificar
  `configuration.yaml`.
- Validación de conectividad con el endpoint `/api/health` del backend.
- Descubrimiento del registro de áreas, dispositivos y entidades de Home
  Assistant.
- Publicación del catálogo y resincronización automática cuando cambian los
  registros de Home Assistant.
- Sincronización con el perfil activo del backend para escuchar únicamente las
  entidades seleccionadas.
- Normalización y envío de cambios de estado al endpoint `/api/events`.
- Entidades nativas para consultar ocupación, habitación actual y cantidad
  estimada de personas.
- Panel lateral integrado, con acceso directo HTTPS o proxy autenticado a
  través de Home Assistant.
- Servicios para probar eventos, actualizar el catálogo, iniciar replay y
  administrar sensores de prueba aislados.
- Endpoint autenticado de diagnóstico con el estado del bridge.

## Responsabilidades del bridge y del backend

El bridge realiza tareas vinculadas con Home Assistant:

1. Lee el catálogo local de áreas y entidades.
2. Publica el catálogo en el backend.
3. Obtiene desde el backend la selección del perfil activo.
4. Escucha y reenvía cambios solo para entidades habilitadas y existentes en
   la instalación local.
5. Actualiza las entidades de salida con las respuestas de eventos y con una
   consulta periódica de respaldo.
6. Ejecuta acciones de Home Assistant solicitadas por el panel, como crear o
   eliminar recursos de prueba.

El backend administra los perfiles, el procesamiento histórico, la inferencia,
el estado del simulador y la interfaz web. Las entidades Frigate seleccionadas
como confirmaciones de persona o mascota se reenvían como cualquier otra
entidad habilitada; el backend decide cómo almacenarlas y utilizarlas como
etiquetas de entrenamiento. El bridge no las convierte directamente en
presencia.

## Requisitos

- Home Assistant 2026.1.0 o posterior.
- HACS instalado.
- Backend Transformer Presence en ejecución y alcanzable desde Home Assistant
  Core.

Ejemplo de URL del backend:

```text
http://192.168.1.50:8081
```

Si el backend se encuentra en otro equipo, utiliza su IP de red, nombre DNS o
dirección Tailscale. `127.0.0.1` solo es correcto cuando Home Assistant Core y
el backend comparten el mismo host o contenedor de red.

## Instalación con HACS

1. Abre HACS en Home Assistant.
2. Ve a `Integrations` y abre el menú de repositorios personalizados.
3. Agrega este repositorio como tipo `Integration`:

   ```text
   https://github.com/GuerraF8/transformer-presence-hacs
   ```

4. Descarga `Transformer Presence Bridge`.
5. Reinicia Home Assistant.
6. Ve a `Settings > Devices & services > Add integration`.
7. Busca `Transformer Presence Bridge` y completa la configuración.

## Configuración

La integración ofrece estas opciones:

- **URL interna del backend para Home Assistant:** dirección HTTP o HTTPS que
  Home Assistant Core utiliza para consultar y publicar datos.
- **URL pública HTTPS del panel:** dirección opcional para cargar directamente
  la interfaz del backend. Si se omite o no utiliza HTTPS, el panel se sirve
  mediante el proxy de la integración.
- **Modo desarrollador:** habilita en el panel las herramientas de replay y el
  acceso al simulador.
- **Entidades disponibles para catálogo:** lista opcional de `entity_id`
  separados por comas. Sirve como selección inicial explícita; el perfil activo
  del backend determina qué cambios de estado se reenvían finalmente.

La configuración queda almacenada en la entrada de Home Assistant y puede
modificarse desde sus opciones. Al guardar una URL del backend, la integración
comprueba que `/api/health` sea accesible.

### Panel y acceso remoto

El panel lateral añade los parámetros `embedded=1` y `dev=0|1` a la URL sin
eliminar parámetros existentes.

- Si se configura una URL pública HTTPS, Home Assistant carga esa dirección de
  forma directa.
- Si la URL pública está vacía o usa HTTP, la integración publica el panel bajo
  el origen de Home Assistant mediante un token interno y reenvía HTTP y
  WebSocket al backend configurado.

El proxy evita contenido mixto cuando Home Assistant se abre mediante HTTPS,
por ejemplo, con Home Assistant Cloud. El destino del proxy proviene de la
entrada de configuración y no puede ser elegido por el navegador.

Ejemplo para un backend en la red local y acceso remoto mediante Home Assistant
Cloud:

```text
URL interna del backend para Home Assistant: http://192.168.0.221:8081
URL pública HTTPS del panel:                 (vacía)
```

## Catálogo y reenvío de eventos

El catálogo incluye las entidades disponibles y las áreas registradas. Para
cada entidad se informa su dominio, estado, tipo de sensor inferido, habitación,
clase de dispositivo, plataforma y procedencia del área. El área asignada a la
entidad tiene prioridad sobre el área heredada desde su dispositivo.

El catálogo distingue como compatibles los sensores de movimiento, apertura u
ocupación pertenecientes a dominios habituales como `binary_sensor`, `sensor`,
`person`, `device_tracker`, `input_boolean`, `switch`, `cover` y `lock`. Las
demás entidades también pueden aparecer en el inventario para que el backend
disponga del contexto completo.

La integración reenvía un cambio de estado solamente cuando:

- El backend incluyó la entidad en `enabled_entities` para el perfil activo.
- El `entity_id` continúa presente en el catálogo de esta instalación.
- El estado realmente cambió.
- El nuevo estado no es `unknown` ni `unavailable`.
- La entidad no es una salida generada por la propia integración.

El evento enviado contiene `entity_id`, estado, tipo de sensor, habitación,
marca temporal y origen.

## Entidades para automatizaciones

Las salidas se agrupan bajo el dispositivo `Inferencia de presencia`:

- `binary_sensor.inferencia_presencia_hogar`: activo cuando existe al menos una
  habitación ocupada.
- `binary_sensor.inferencia_presencia_<habitacion>`: ocupación inferida de cada
  habitación conocida por el backend.
- `sensor.inferencia_presencia_habitacion_actual`: habitación inferida o
  `sin_presencia`.
- `sensor.inferencia_presencia_personas_estimadas`: cantidad estimada de
  personas.

Las entidades se actualizan inmediatamente cuando `/api/events` devuelve un
estado de presencia. Además, la integración consulta `/api/sim_data` cada cinco
segundos como mecanismo de respaldo. Tras tres fallos consecutivos del backend,
las entidades pasan a `unavailable` en lugar de publicar una ausencia falsa.

Home Assistant puede agregar un sufijo al `entity_id` si ya existe una entidad
con el mismo nombre. Utiliza el identificador mostrado en
`Settings > Devices & services > Entities` al crear automatizaciones.

Ejemplo:

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

El historial de estas entidades queda disponible mediante Recorder cuando ese
componente estándar de Home Assistant está habilitado.

## Servicios

La integración registra los siguientes servicios:

| Servicio | Propósito |
| --- | --- |
| `inferencia_presencia.emitir_evento_prueba` | Envía un evento sintético al backend sin crear una entidad real. |
| `inferencia_presencia.iniciar_replay_historico` | Solicita al backend la reproducción de un CSV accesible desde su contenedor. |
| `inferencia_presencia.refrescar_catalogo_sensores` | Vuelve a escanear áreas y entidades y publica el catálogo. |
| `inferencia_presencia.crear_sensores_prueba` | Crea switches propios para probar movimiento y ocupación por habitación. |
| `inferencia_presencia.eliminar_sensores_prueba` | Elimina únicamente los switches registrados como propios. |
| `inferencia_presencia.eliminar_recursos_prueba` | Elimina los switches propios y las áreas de prueba que hayan quedado vacías. |

Los campos y selectores de cada servicio aparecen en
`Developer tools > Actions` dentro de Home Assistant.

## Recursos de prueba y seguridad

Los sensores de prueba se crean como `switch.inferencia_*_test` dentro de áreas
`Inferencia prueba · <habitación>`. Sus identificadores se guardan mediante
`homeassistant.helpers.storage.Store`.

La limpieza solo elimina recursos registrados como propios. Un área se
conserva si contiene una entidad o un dispositivo ajeno a la integración. El
bridge no modifica entidades existentes de otros dominios.

El endpoint de estado, el endpoint de acciones y el proxy del panel requieren
autenticación de Home Assistant. El token del proxy se genera para la entrada
activa y el navegador no puede proporcionar un backend alternativo.

## Diagnóstico

Con una sesión autenticada de Home Assistant se puede consultar:

```text
GET /api/inferencia_presencia/status
```

La respuesta incluye la URL activa del backend, el catálogo detectado, las
entidades habilitadas, los eventos recientes, contadores de envíos, errores y
el estado de actualización de las entidades de presencia.

## Desarrollo y validación

Instala las dependencias de prueba y ejecuta la suite desde la raíz del
repositorio:

```bash
python -m pip install -r requirements_test.txt
python -m pytest
```

El workflow de GitHub Actions ejecuta la validación de HACS, las pruebas y los
umbrales de cobertura en cada cambio relevante.

## Backend

El backend se distribuye por separado:

```text
https://github.com/GuerraF8/transformer-presence-backend
```

El despliegue recomendado consiste en instalar esta integración mediante HACS
y ejecutar el backend con su configuración de Docker.

## Licencia

Este proyecto se distribuye bajo la licencia [MIT](LICENSE).
