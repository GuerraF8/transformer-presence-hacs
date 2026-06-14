from __future__ import annotations

import re
from typing import Any

NO_PRESENCE = "sin_presencia"


def room_slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9_]+", "_", value.strip().lower().replace(" ", "_"))
    return re.sub(r"_+", "_", slug).strip("_") or "desconocida"


def _rooms(value: Any) -> list[str]:
    if not isinstance(value, (list, tuple, set)):
        return []
    result: list[str] = []
    for item in value:
        room = str(item or "").strip().lower()
        if room and room not in result:
            result.append(room)
    return result


def _integer(value: Any, fallback: int = 0) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return fallback


def _number(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _presence_bool(value: Any, fallback: bool) -> bool:
    if isinstance(value, bool):
        return value
    normalized = str(value or "").strip().lower()
    if normalized in {"presente", "present", "on", "true", "1"}:
        return True
    if normalized in {"ausente", "absent", "off", "false", "0"}:
        return False
    return fallback


def unavailable_presence_data() -> dict[str, Any]:
    return {
        "rooms": [],
        "active_rooms": [],
        "inferred_presence": False,
        "current_room": NO_PRESENCE,
        "people_estimate": 0,
        "confidence": None,
        "updated_at": None,
        "input_mode": "unknown",
        "model": "unknown",
        "service_available": False,
        "consecutive_failures": 0,
    }


def normalize_snapshot(payload: dict[str, Any]) -> dict[str, Any]:
    presence = payload.get("presence")
    presence = presence if isinstance(presence, dict) else {}
    evaluation = payload.get("evaluation")
    evaluation = evaluation if isinstance(evaluation, dict) else {}
    people_metrics = evaluation.get("people")
    people_metrics = people_metrics if isinstance(people_metrics, dict) else {}
    meta = payload.get("meta")
    meta = meta if isinstance(meta, dict) else {}
    replay = payload.get("replay")
    replay = replay if isinstance(replay, dict) else {}
    model = payload.get("model")
    model = model if isinstance(model, dict) else {}
    profile = payload.get("profile")
    profile = profile if isinstance(profile, dict) else {}
    events = payload.get("events")
    latest_event = events[-1] if isinstance(events, list) and events else {}
    latest_event = latest_event if isinstance(latest_event, dict) else {}

    rooms = _rooms(payload.get("rooms"))
    active_rooms = _rooms(presence.get("active_rooms"))
    inferred_presence = _presence_bool(
        presence.get("inferred_presence"),
        bool(active_rooms),
    )
    current_room = str(presence.get("current_room") or "").strip().lower()
    if not inferred_presence or not active_rooms:
        current_room = NO_PRESENCE

    people_estimate = _integer(
        presence.get(
            "people_estimate",
            people_metrics.get("current_estimate", 0),
        )
    )
    input_mode = str(
        meta.get("input_mode") or replay.get("mode") or "listen"
    ).strip().lower()
    model_name = str(meta.get("inference_mode") or "").strip()
    if not model_name:
        model_name = "ai_probabilistic_presence" if model.get("ready") else "rule_based"

    return {
        "rooms": rooms,
        "active_rooms": active_rooms,
        "inferred_presence": inferred_presence,
        "current_room": current_room or NO_PRESENCE,
        "people_estimate": people_estimate,
        "confidence": _number(
            presence.get("confidence", latest_event.get("presence_confidence"))
        ),
        "updated_at": presence.get("updated_at") or latest_event.get("timestamp"),
        "input_mode": input_mode,
        "model": model_name,
        "profile_id": profile.get("active_profile_id"),
        "profile_name": profile.get("name"),
        "profile_revision": profile.get("revision"),
        "service_available": (
            bool(profile.get("available")) if profile else True
        ),
        "consecutive_failures": 0,
    }


def normalize_event_response(
    payload: dict[str, Any],
    previous: dict[str, Any] | None,
) -> dict[str, Any] | None:
    current = dict(previous or unavailable_presence_data())
    input_mode = str(payload.get("input_mode") or current.get("input_mode") or "listen")
    input_mode = input_mode.strip().lower()

    if payload.get("status") == "ignored":
        current["input_mode"] = input_mode
        current["service_available"] = payload.get("reason") != "no_active_profile"
        current["consecutive_failures"] = 0
        return current

    event = payload.get("event")
    event = event if isinstance(event, dict) else {}
    recognized_fields = {
        "presencia_inferida",
        "habitacion_inferida_ia",
        "habitaciones_activas",
        "personas_estimadas",
        "confianza_presencia",
    }
    if not event and not recognized_fields.intersection(payload):
        return None

    active_rooms = _rooms(payload.get("habitaciones_activas", event.get("active_rooms")))
    inferred_presence = _presence_bool(
        payload.get("presencia_inferida", event.get("inferred_presence")),
        bool(active_rooms),
    )
    room = str(
        payload.get("habitacion_inferida_ia")
        or event.get("presence_room")
        or ""
    ).strip().lower()
    if not inferred_presence or not active_rooms:
        room = NO_PRESENCE

    known_rooms = _rooms(current.get("rooms"))
    for candidate in [*active_rooms, room]:
        if candidate and candidate != NO_PRESENCE and candidate not in known_rooms:
            known_rooms.append(candidate)

    model_active = payload.get("modelo_ia_activo")
    model_name = current.get("model", "unknown")
    if isinstance(model_active, bool):
        model_name = "ai_probabilistic_presence" if model_active else "rule_based"

    return {
        "rooms": known_rooms,
        "active_rooms": active_rooms,
        "inferred_presence": inferred_presence,
        "current_room": room or NO_PRESENCE,
        "people_estimate": _integer(
            payload.get("personas_estimadas", event.get("estimated_people", 0))
        ),
        "confidence": _number(
            payload.get("confianza_presencia", event.get("presence_confidence"))
        ),
        "updated_at": payload.get("updated_at") or event.get("timestamp"),
        "input_mode": input_mode,
        "model": model_name,
        "profile_id": current.get("profile_id"),
        "profile_name": current.get("profile_name"),
        "profile_revision": current.get("profile_revision"),
        "service_available": True,
        "consecutive_failures": 0,
    }
