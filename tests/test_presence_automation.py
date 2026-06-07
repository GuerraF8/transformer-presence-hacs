from __future__ import annotations

from homeassistant.setup import async_setup_component


async def test_room_presence_triggers_external_automation(hass) -> None:
    assert await async_setup_component(
        hass,
        "input_boolean",
        {
            "input_boolean": {
                "presence_action_observed": {
                    "name": "Presence action observed",
                    "initial": False,
                }
            }
        },
    )
    assert await async_setup_component(
        hass,
        "automation",
        {
            "automation": [
                {
                    "alias": "HU-04 presence trigger",
                    "trigger": [
                        {
                            "platform": "state",
                            "entity_id": "binary_sensor.inferencia_presencia_kitchen",
                            "from": "off",
                            "to": "on",
                        }
                    ],
                    "action": [
                        {
                            "service": "input_boolean.turn_on",
                            "target": {
                                "entity_id": "input_boolean.presence_action_observed"
                            },
                        }
                    ],
                }
            ]
        },
    )
    await hass.async_block_till_done()

    hass.states.async_set("binary_sensor.inferencia_presencia_kitchen", "off")
    await hass.async_block_till_done()
    hass.states.async_set("binary_sensor.inferencia_presencia_kitchen", "on")
    await hass.async_block_till_done()

    observed = hass.states.get("input_boolean.presence_action_observed")
    assert observed is not None
    assert observed.state == "on"
