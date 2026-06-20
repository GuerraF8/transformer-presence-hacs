from __future__ import annotations

from custom_components.inferencia_presencia.presence import (
    NO_PRESENCE,
    normalize_event_response,
    normalize_snapshot,
)


def snapshot(
    *,
    rooms: list[str] | None = None,
    active_rooms: list[str] | None = None,
    input_mode: str = "listen",
    room_labels: dict[str, str] | None = None,
    profile_room_labels: dict[str, str] | None = None,
    layout_version: int = 1,
    layout_source: str = "profile",
) -> dict:
    payload = {
        "rooms": rooms or ["bedroom", "kitchen"],
        "meta": {
            "input_mode": input_mode,
            "inference_mode": "rule_based",
        },
        "presence": {
            "current_room": (active_rooms or [None])[0],
            "active_rooms": active_rooms or [],
            "inferred_presence": bool(active_rooms),
            "people_estimate": len(active_rooms or []),
            "confidence": 0.87,
            "updated_at": "2026-06-06T12:00:00+00:00",
        },
    }
    payload["layout_reference"] = {
        "version": layout_version,
        "source": layout_source,
        "room_labels": room_labels or {},
    }
    if profile_room_labels is not None:
        payload["profile"] = {
            "available": True,
            "active_profile_id": "profile-1",
            "room_labels": profile_room_labels,
        }
    return payload


def test_normalizes_presence_and_absence() -> None:
    occupied = normalize_snapshot(snapshot(active_rooms=["kitchen"]))
    absent = normalize_snapshot(snapshot(active_rooms=[]))

    assert occupied["active_rooms"] == ["kitchen"]
    assert occupied["current_room"] == "kitchen"
    assert occupied["people_estimate"] == 1
    assert absent["current_room"] == NO_PRESENCE
    assert absent["inferred_presence"] is False


def test_normalizes_layout_labels_with_profile_fallback() -> None:
    normalized = normalize_snapshot(
        snapshot(
            rooms=["kitchen", "home_office", "hall"],
            room_labels={
                "kitchen": "Cocina principal",
                "hall": "",
                "removed": "Ignorada",
            },
            profile_room_labels={
                "kitchen": "Cocina antigua",
                "home_office": "Oficina",
                "hall": "Pasillo",
            },
            layout_version=7,
            layout_source="profile",
        )
    )

    assert normalized["room_labels"] == {
        "kitchen": "Cocina principal",
        "home_office": "Oficina",
        "hall": "Pasillo",
    }
    assert normalized["layout_version"] == 7
    assert normalized["layout_source"] == "profile"


def test_confirmation_response_does_not_replace_presence_state() -> None:
    previous = normalize_snapshot(snapshot(active_rooms=["kitchen"]))
    result = normalize_event_response(
        {
            "status": "recorded",
            "reason": "training_confirmation",
            "training_role": "person_confirmation",
            "input_mode": "listen",
        },
        previous,
    )
    assert result is None


def test_snapshot_without_active_profile_is_unavailable() -> None:
    payload = snapshot(active_rooms=[])
    payload["profile"] = {"available": False, "active_profile_id": None}

    normalized = normalize_snapshot(payload)

    assert normalized["service_available"] is False


def test_event_response_updates_immediately_and_adds_new_room() -> None:
    previous = normalize_snapshot(snapshot(active_rooms=[]))

    updated = normalize_event_response(
        {
            "presencia_inferida": "Presente",
            "habitacion_inferida_ia": "office",
            "habitaciones_activas": ["office"],
            "personas_estimadas": 1,
            "confianza_presencia": 0.93,
            "input_mode": "listen",
            "updated_at": "2026-06-06T12:00:01+00:00",
        },
        previous,
    )

    assert updated is not None
    assert updated["current_room"] == "office"
    assert "office" in updated["rooms"]
    assert updated["confidence"] == 0.93


def test_ignored_event_only_updates_input_mode() -> None:
    previous = normalize_snapshot(snapshot(active_rooms=["kitchen"]))

    updated = normalize_event_response(
        {
            "status": "ignored",
            "reason": "real_sensors_not_active",
            "input_mode": "replay",
        },
        previous,
    )

    assert updated is not None
    assert updated["active_rooms"] == ["kitchen"]
    assert updated["input_mode"] == "replay"


def test_no_active_profile_marks_entities_unavailable_without_forcing_off() -> None:
    previous = normalize_snapshot(snapshot(active_rooms=["kitchen"]))

    updated = normalize_event_response(
        {
            "status": "ignored",
            "reason": "no_active_profile",
            "input_mode": "listen",
        },
        previous,
    )

    assert updated is not None
    assert updated["service_available"] is False
    assert updated["active_rooms"] == ["kitchen"]


def test_unstructured_success_does_not_replace_last_state() -> None:
    previous = normalize_snapshot(snapshot(active_rooms=["kitchen"]))

    assert normalize_event_response({"raw": "ok"}, previous) is None
