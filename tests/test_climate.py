"""Tests for flows, preview and entity behaviour (SPEC.md references in names)."""

from __future__ import annotations

from typing import Any

from homeassistant import config_entries
from homeassistant.components.climate import (
    ATTR_FAN_MODE,
    ATTR_HVAC_ACTION,
    ATTR_HVAC_MODE,
    ATTR_PRESET_MODE,
    ATTR_TARGET_TEMP_HIGH,
    ATTR_TARGET_TEMP_LOW,
    DOMAIN as CLIMATE_DOMAIN,
    SERVICE_SET_FAN_MODE,
    SERVICE_SET_HVAC_MODE,
    SERVICE_SET_PRESET_MODE,
    SERVICE_SET_TEMPERATURE,
    SERVICE_TURN_ON,
    ClimateEntityFeature,
)
from homeassistant.const import ATTR_ENTITY_ID, ATTR_SUPPORTED_FEATURES, ATTR_TEMPERATURE
from homeassistant.core import HomeAssistant, State
from homeassistant.data_entry_flow import FlowResultType, InvalidData
from homeassistant.helpers import device_registry as dr, entity_registry as er
import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_mock_service,
    mock_restore_cache,
)

from custom_components.climate_template_ui.const import DOMAIN

ENTITY_ID = "climate.living_ac"


def _options(**overrides: Any) -> dict[str, Any]:
    """Options as the form would submit them."""
    base: dict[str, Any] = {
        "name": "Living AC",
        "state_templates": {},
        "actions": {},
        "modes_limits": {
            "modes": ["off", "heat", "cool", "heat_cool"],
            "fan_modes": ["auto", "low", "high"],
            "preset_modes": ["eco", "comfort"],
            "swing_modes": ["on", "off"],
            "min_temp": 16.0,
            "max_temp": 30.0,
            "temp_step": 0.5,
        },
        "advanced": {},
    }
    for key, value in overrides.items():
        base[key] = {**base[key], **value} if isinstance(value, dict) else value
    return base


async def _setup(hass: HomeAssistant, options: dict[str, Any]) -> MockConfigEntry:
    entry = MockConfigEntry(domain=DOMAIN, title=options["name"], data={}, options=options)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


# ---------------------------------------------------------------------------
# §2 Config flow / options flow
# ---------------------------------------------------------------------------
async def test_config_flow_creates_entry(hass: HomeAssistant) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["preview"] == DOMAIN

    user_input = _options(state_templates={"current_temperature_template": "{{ 21.5 }}"})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], user_input)
    await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Living AC"
    state = hass.states.get(ENTITY_ID)
    assert state is not None
    assert state.attributes["current_temperature"] == 21.5


async def test_config_flow_defaults_from_sections(hass: HomeAssistant) -> None:
    """Untouched collapsed sections get the upstream defaults (§3.3)."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            "name": "Living AC",
            "state_templates": {},
            "actions": {},
            "modes_limits": {},
            "advanced": {},
        },
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    modes = result["options"]["modes_limits"]
    assert modes["modes"] == ["auto", "off", "cool", "heat", "dry", "fan_only"]
    assert modes["min_temp"] == 7.0
    assert modes["max_temp"] == 35.0


@pytest.mark.parametrize(
    ("override", "section", "error"),
    [
        (
            {"advanced": {"attributes": {"room": "{{ states('x' }}"}}},
            "advanced",
            "invalid_template",
        ),
        ({"modes_limits": {"min_temp": 30.0, "max_temp": 20.0}}, "modes_limits", "min_max_temp"),
        ({"modes_limits": {"modes": []}}, "modes_limits", "no_hvac_modes"),
        ({"actions": {"set_hvac_mode": [{"not_an_action": 1}]}}, "actions", "invalid_action"),
        (
            {
                "actions": {"set_fan_mode": [{"action": "test.x"}]},
                "modes_limits": {"fan_modes": []},
            },
            "modes_limits",
            "empty_mode_list",
        ),
    ],
)
async def test_config_flow_errors(
    hass: HomeAssistant, override: dict[str, Any], section: str, error: str
) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(result["flow_id"], _options(**override))
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {section: error}
    assert result["description_placeholders"]["field"]


async def test_template_selector_rejects_bad_syntax(hass: HomeAssistant) -> None:
    """TemplateSelector validates syntax at schema level (field-level error)."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    with pytest.raises(InvalidData):
        await hass.config_entries.flow.async_configure(
            result["flow_id"],
            _options(state_templates={"hvac_mode_template": "{{ states('x' }}"}),
        )


async def test_options_flow_updates_and_reloads(hass: HomeAssistant) -> None:
    entry = await _setup(hass, _options())
    assert hass.states.get(ENTITY_ID).attributes["max_temp"] == 30.0

    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    new = _options(modes_limits={"max_temp": 28.0})
    new.pop("name")
    result = await hass.config_entries.options.async_configure(result["flow_id"], new)
    await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options["name"] == "Living AC"
    assert hass.states.get(ENTITY_ID).attributes["max_temp"] == 28.0


# ---------------------------------------------------------------------------
# §2.4 Preview
# ---------------------------------------------------------------------------
async def test_preview_config_flow(hass: HomeAssistant, hass_ws_client) -> None:
    hass.states.async_set("sensor.room", "22.3")
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    client = await hass_ws_client(hass)
    await client.send_json_auto_id(
        {
            "type": f"{DOMAIN}/start_preview",
            "flow_id": result["flow_id"],
            "flow_type": "config_flow",
            "user_input": _options(
                state_templates={
                    "current_temperature_template": "{{ states('sensor.room') }}",
                    "hvac_mode_template": "heat",
                }
            ),
        }
    )
    msg = await client.receive_json()
    assert msg["success"]
    msg = await client.receive_json()
    event = msg["event"]
    assert event["domain"] == "climate"
    assert event["state"] == "heat"
    assert event["attributes"]["current_temperature"] == 22.3

    # Live update while the form is open.
    hass.states.async_set("sensor.room", "23.0")
    msg = await client.receive_json()
    assert msg["event"]["attributes"]["current_temperature"] == 23.0


async def test_preview_reports_invalid_input(hass: HomeAssistant, hass_ws_client) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    client = await hass_ws_client(hass)
    await client.send_json_auto_id(
        {
            "type": f"{DOMAIN}/start_preview",
            "flow_id": result["flow_id"],
            "flow_type": "config_flow",
            "user_input": _options(modes_limits={"min_temp": 40.0}),
        }
    )
    assert (await client.receive_json())["success"]
    assert "min_max_temp" in (await client.receive_json())["event"]["error"]


async def test_preview_options_flow(hass: HomeAssistant, hass_ws_client) -> None:
    entry = await _setup(hass, _options())
    result = await hass.config_entries.options.async_init(entry.entry_id)
    client = await hass_ws_client(hass)
    user_input = _options(state_templates={"hvac_mode_template": "cool"})
    user_input.pop("name")
    await client.send_json_auto_id(
        {
            "type": f"{DOMAIN}/start_preview",
            "flow_id": result["flow_id"],
            "flow_type": "options_flow",
            "user_input": user_input,
        }
    )
    assert (await client.receive_json())["success"]
    event = (await client.receive_json())["event"]
    assert event["state"] == "cool"
    assert event["attributes"]["friendly_name"] == "Living AC"


# ---------------------------------------------------------------------------
# §4 Entity behaviour
# ---------------------------------------------------------------------------
async def test_optimistic_mode_without_templates(hass: HomeAssistant) -> None:
    await _setup(hass, _options())
    state = hass.states.get(ENTITY_ID)
    assert state.state == "off"
    # §4.3 no template/action → no fan/preset/swing/temperature features.
    features = state.attributes[ATTR_SUPPORTED_FEATURES]
    assert not features & ClimateEntityFeature.FAN_MODE
    assert not features & ClimateEntityFeature.TARGET_TEMPERATURE

    await hass.services.async_call(
        CLIMATE_DOMAIN,
        SERVICE_SET_HVAC_MODE,
        {ATTR_ENTITY_ID: ENTITY_ID, ATTR_HVAC_MODE: "cool"},
        blocking=True,
    )
    assert hass.states.get(ENTITY_ID).state == "cool"


async def test_templates_drive_state(hass: HomeAssistant) -> None:
    hass.states.async_set("input_select.mode", "heat")
    hass.states.async_set("sensor.target", "22.5")
    await _setup(
        hass,
        _options(
            state_templates={
                "hvac_mode_template": "{{ states('input_select.mode') }}",
                "target_temperature_template": "{{ states('sensor.target') }}",
                "hvac_action_template": (
                    "{{ 'heating' if is_state('input_select.mode', 'heat') else 'idle' }}"
                ),
                "fan_mode_template": "{{ 'low' }}",
                "preset_mode_template": "{{ 'eco' }}",
            }
        ),
    )
    state = hass.states.get(ENTITY_ID)
    assert state.state == "heat"
    assert state.attributes[ATTR_TEMPERATURE] == 22.5
    assert state.attributes[ATTR_HVAC_ACTION] == "heating"
    assert state.attributes[ATTR_FAN_MODE] == "low"
    assert state.attributes[ATTR_PRESET_MODE] == "eco"
    features = state.attributes[ATTR_SUPPORTED_FEATURES]
    assert features & ClimateEntityFeature.FAN_MODE
    assert features & ClimateEntityFeature.PRESET_MODE
    assert features & ClimateEntityFeature.TARGET_TEMPERATURE

    hass.states.async_set("input_select.mode", "cool")
    await hass.async_block_till_done()
    state = hass.states.get(ENTITY_ID)
    assert state.state == "cool"
    assert state.attributes[ATTR_HVAC_ACTION] == "idle"

    # Invalid template output is ignored (state kept) — §4.2.
    hass.states.async_set("input_select.mode", "bogus")
    await hass.async_block_till_done()
    assert hass.states.get(ENTITY_ID).state == "cool"


async def test_shared_template_text(hass: HomeAssistant) -> None:
    """Two keys with identical template text must both update (§4.2)."""
    await _setup(
        hass,
        _options(
            state_templates={
                "current_temperature_template": "{{ 20 }}",
                "target_temperature_template": "{{ 20 }}",
            }
        ),
    )
    state = hass.states.get(ENTITY_ID)
    assert state.attributes["current_temperature"] == 20
    assert state.attributes[ATTR_TEMPERATURE] == 20


async def test_actions_receive_variables(hass: HomeAssistant) -> None:
    calls = async_mock_service(hass, "test", "record")
    record = lambda **data: [{"action": "test.record", "data": data}]  # noqa: E731
    await _setup(
        hass,
        _options(
            actions={
                "set_hvac_mode": record(mode="{{ hvac_mode }}", who="{{ this.entity_id }}"),
                "set_temperature": record(t="{{ temperature }}", room="{{ room }}"),
                "set_fan_mode": record(fan="{{ fan_mode }}"),
                "set_preset_mode": record(preset="{{ preset_mode }}"),
            },
            advanced={"variables": {"room": "living"}},
        ),
    )
    await hass.services.async_call(
        CLIMATE_DOMAIN,
        SERVICE_SET_HVAC_MODE,
        {ATTR_ENTITY_ID: ENTITY_ID, ATTR_HVAC_MODE: "heat"},
        blocking=True,
    )
    await hass.services.async_call(
        CLIMATE_DOMAIN,
        SERVICE_SET_TEMPERATURE,
        {ATTR_ENTITY_ID: ENTITY_ID, ATTR_TEMPERATURE: 23},
        blocking=True,
    )
    await hass.services.async_call(
        CLIMATE_DOMAIN,
        SERVICE_SET_FAN_MODE,
        {ATTR_ENTITY_ID: ENTITY_ID, ATTR_FAN_MODE: "high"},
        blocking=True,
    )
    await hass.services.async_call(
        CLIMATE_DOMAIN,
        SERVICE_SET_PRESET_MODE,
        {ATTR_ENTITY_ID: ENTITY_ID, ATTR_PRESET_MODE: "eco"},
        blocking=True,
    )
    assert [c.data for c in calls] == [
        {"mode": "heat", "who": ENTITY_ID},
        {"t": 23, "room": "living"},
        {"fan": "high"},
        {"preset": "eco"},
    ]
    state = hass.states.get(ENTITY_ID)
    assert state.state == "heat"
    assert state.attributes[ATTR_TEMPERATURE] == 23
    assert state.attributes[ATTR_FAN_MODE] == "high"


async def test_heat_cool_range(hass: HomeAssistant) -> None:
    calls = async_mock_service(hass, "test", "record")
    await _setup(
        hass,
        _options(
            actions={
                "set_temperature": [
                    {
                        "action": "test.record",
                        "data": {"low": "{{ target_temp_low }}", "high": "{{ target_temp_high }}"},
                    }
                ]
            }
        ),
    )
    features = hass.states.get(ENTITY_ID).attributes[ATTR_SUPPORTED_FEATURES]
    assert features & ClimateEntityFeature.TARGET_TEMPERATURE_RANGE
    assert features & ClimateEntityFeature.TARGET_TEMPERATURE

    await hass.services.async_call(
        CLIMATE_DOMAIN,
        SERVICE_SET_TEMPERATURE,
        {
            ATTR_ENTITY_ID: ENTITY_ID,
            ATTR_HVAC_MODE: "heat_cool",
            ATTR_TARGET_TEMP_LOW: 19,
            ATTR_TARGET_TEMP_HIGH: 25,
        },
        blocking=True,
    )
    state = hass.states.get(ENTITY_ID)
    assert state.state == "heat_cool"
    assert state.attributes[ATTR_TARGET_TEMP_LOW] == 19
    assert state.attributes[ATTR_TARGET_TEMP_HIGH] == 25
    assert state.attributes[ATTR_TEMPERATURE] is None
    assert calls[-1].data == {"low": 19, "high": 25}


async def test_availability_icon_attributes(hass: HomeAssistant) -> None:
    hass.states.async_set("binary_sensor.node", "on")
    await _setup(
        hass,
        _options(
            advanced={
                "availability": "{{ is_state('binary_sensor.node', 'on') }}",
                "icon": "mdi:air-conditioner",
                "attributes": {"room": "{{ 'living' }}"},
            }
        ),
    )
    state = hass.states.get(ENTITY_ID)
    assert state.state == "off"
    assert state.attributes["icon"] == "mdi:air-conditioner"
    assert state.attributes["room"] == "living"

    hass.states.async_set("binary_sensor.node", "off")
    await hass.async_block_till_done()
    assert hass.states.get(ENTITY_ID).state == "unavailable"


async def test_turn_on_fallback(hass: HomeAssistant) -> None:
    """Modes without heat/cool: turn_on picks the first non-off mode (§4.5)."""
    await _setup(hass, _options(modes_limits={"modes": ["off", "dry", "fan_only"]}))
    await hass.services.async_call(
        CLIMATE_DOMAIN, SERVICE_TURN_ON, {ATTR_ENTITY_ID: ENTITY_ID}, blocking=True
    )
    assert hass.states.get(ENTITY_ID).state == "dry"


async def test_restore_state(hass: HomeAssistant) -> None:
    mock_restore_cache(
        hass,
        [State(ENTITY_ID, "heat", {ATTR_TEMPERATURE: 24.5, ATTR_FAN_MODE: "high"})],
    )
    noop = [{"delay": 0}]
    await _setup(hass, _options(actions={"set_fan_mode": noop, "set_temperature": noop}))
    state = hass.states.get(ENTITY_ID)
    assert state.state == "heat"
    assert state.attributes[ATTR_FAN_MODE] == "high"
    assert state.attributes[ATTR_TEMPERATURE] == 24.5


async def test_device_link(hass: HomeAssistant) -> None:
    other = MockConfigEntry(domain="test")
    other.add_to_hass(hass)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=other.entry_id, identifiers={("test", "ac1")}, name="AC unit"
    )
    entry = await _setup(hass, _options(device_id=device.id))
    registry = er.async_get(hass)
    entity_id = registry.async_get_entity_id(CLIMATE_DOMAIN, DOMAIN, entry.entry_id)
    assert registry.async_get(entity_id).device_id == device.id


async def test_invalid_stored_options(hass: HomeAssistant) -> None:
    """Stored options that no longer validate put the entry in error (§5)."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Broken",
        options=_options(modes_limits={"modes": []}),
    )
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert hass.states.get("climate.broken") is None


async def test_readme_example_actions_validate(hass: HomeAssistant) -> None:
    """Actions shown in the README must pass validation (README §Examples)."""
    from custom_components.climate_template_ui.schema import async_parse_options

    config = await async_parse_options(
        hass,
        _options(
            actions={
                "set_hvac_mode": [
                    {
                        "condition": "state",
                        "entity_id": "input_boolean.enable_aircon_controller",
                        "state": "on",
                    },
                    {
                        "action": "esphome.{{ node }}_aircon_state",
                        "data": {"operation_mode": "{{ hvac_mode }}"},
                    },
                ],
                "set_temperature": [
                    {
                        "action": "remote.send_command",
                        "target": {"entity_id": "remote.bedroom_broadlink"},
                        "data": {
                            "device": "aircon",
                            "command": "{{ 'temp_' ~ (temperature | int) }}",
                        },
                    }
                ],
            },
            advanced={"variables": {"node": "bedroom_node"}},
        ),
    )
    assert set(config.actions) == {"set_hvac_mode", "set_temperature"}
