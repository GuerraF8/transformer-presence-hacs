from custom_components.inferencia_presencia.ha_utils import (
    coerce_bool,
    infer_room,
    infer_sensor_type,
    panel_url_from_backend,
    parse_tracked_entities,
)


def test_panel_url_preserves_existing_query_parameters() -> None:
    url = panel_url_from_backend("https://example.test/panel?token=abc", True)
    assert "token=abc" in url
    assert "embedded=1" in url
    assert "dev=1" in url


def test_entity_inference_and_configuration_helpers() -> None:
    assert infer_sensor_type("binary_sensor.kitchen_motion") == "motion"
    assert infer_room("binary_sensor.kitchen_motion") == "kitchen"
    assert parse_tracked_entities(" sensor.one, binary_sensor.two ") == {
        "sensor.one",
        "binary_sensor.two",
    }
    assert coerce_bool("off", True) is False
