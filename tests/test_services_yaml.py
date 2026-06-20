from pathlib import Path

import yaml


def test_select_options_are_strings() -> None:
    services_path = (
        Path(__file__).parents[1]
        / "custom_components"
        / "inferencia_presencia"
        / "services.yaml"
    )
    services = yaml.safe_load(services_path.read_text(encoding="utf-8"))
    fields = services["crear_sensores_prueba"]["fields"]

    assert fields["initial_state"]["selector"]["select"]["options"] == [
        "off",
        "on",
    ]
