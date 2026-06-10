from __future__ import annotations

import re
from typing import Any
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse, urlunparse

from .const import DEFAULT_DEV_MODE

DEFAULT_AUTO_DOMAINS = {
    "binary_sensor",
    "sensor",
    "person",
    "device_tracker",
    "input_boolean",
    "switch",
    "cover",
    "lock",
}
MOTION_KEYWORDS = {"motion", "pir", "movement", "presence", "detector"}
DOOR_KEYWORDS = {"door", "contact", "window", "gate", "entrance", "entry"}
OCCUPANCY_KEYWORDS = {"occupied", "occupancy", "home", "away", "present"}
ROOM_STOPWORDS = {
    "binary", "sensor", "device", "tracker", "input", "boolean", "status",
    "state", "motion", "pir", "movement", "presence", "detector", "door",
    "contact", "window", "occupancy", "occupied", "person",
}
ROOM_ALIASES = {
    "study": "sittingroom",
    "tvroom": "entertainment_room",
    "tv_room": "entertainment_room",
}


def tokenize(value: str) -> list[str]:
    normalized = value.replace(".", "_").replace("-", "_").lower()
    return [token for token in normalized.split("_") if token]


def infer_sensor_type(entity_id: str) -> str:
    domain = entity_id.split(".", 1)[0].lower() if "." in entity_id else ""
    if domain in {"person", "device_tracker"}:
        return "occupancy"
    tokens = set(tokenize(entity_id))
    if tokens & DOOR_KEYWORDS:
        return "door"
    if tokens & OCCUPANCY_KEYWORDS:
        return "occupancy"
    if tokens & MOTION_KEYWORDS:
        return "motion"
    return "other"


def infer_room(entity_id: str) -> str:
    object_id = entity_id.split(".", 1)[1] if "." in entity_id else entity_id
    useful = [token for token in tokenize(object_id) if token not in ROOM_STOPWORDS]
    room = "_".join(useful) if useful else object_id.lower().replace(".", "_")
    return ROOM_ALIASES.get(room, room)


def parse_tracked_entities(raw_value: str) -> set[str]:
    return {item.strip().lower() for item in raw_value.split(",") if item.strip()}


def safe_room_slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9_]+", "_", value.strip().lower().replace(" ", "_"))
    return re.sub(r"_+", "_", slug).strip("_")


def build_url(base_url: str, path: str) -> str:
    return urljoin(base_url.rstrip("/") + "/", path.lstrip("/"))


def panel_url_from_backend(
    base_url: str, dev_mode: bool = DEFAULT_DEV_MODE
) -> str:
    parsed = urlparse(base_url)
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    query["embedded"] = "1"
    query["dev"] = "1" if dev_mode else "0"
    return urlunparse(
        parsed._replace(path=parsed.path or "/", query=urlencode(query))
    )


def resolve_panel_url(panel_url: str, backend_url: str, dev_mode: bool) -> str:
    return panel_url_from_backend(panel_url or backend_url, dev_mode)


def entity_supported(entity_id: str, sensor_type: str) -> bool:
    domain = entity_id.split(".", 1)[0].lower() if "." in entity_id else ""
    return domain in DEFAULT_AUTO_DOMAINS and sensor_type in {
        "motion", "door", "occupancy"
    }


def coerce_bool(value: Any, fallback: bool = True) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return fallback
    normalized = str(value).strip().lower()
    if normalized in {"1", "true", "yes", "on", "incluir"}:
        return True
    if normalized in {"0", "false", "no", "off", "omitir"}:
        return False
    return fallback
