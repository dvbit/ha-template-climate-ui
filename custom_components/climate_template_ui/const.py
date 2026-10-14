"""Constants for Template Climate UI.

Every key below maps to a section of SPEC.md (§ references in comments).
Option keys deliberately keep the names used by the upstream YAML integration
(jcwillox/hass-template-climate) so users can port existing configs 1:1.
"""

from __future__ import annotations

from typing import Final

from homeassistant.components.climate import (
    DEFAULT_MAX_TEMP,
    DEFAULT_MIN_TEMP,
    FAN_AUTO,
    FAN_HIGH,
    FAN_LOW,
    FAN_MEDIUM,
    PRESET_ACTIVITY,
    PRESET_AWAY,
    PRESET_BOOST,
    PRESET_COMFORT,
    PRESET_ECO,
    PRESET_HOME,
    PRESET_SLEEP,
    HVACMode,
)
from homeassistant.const import STATE_OFF, STATE_ON

# §1.1 New domain: coexists with the upstream `climate_template` integration.
DOMAIN: Final = "climate_template_ui"

# ---------------------------------------------------------------------------
# §2 Config flow: top-level fields and section keys
# ---------------------------------------------------------------------------
CONF_DEVICE_ID: Final = "device_id"

SECTION_STATE: Final = "state_templates"
SECTION_ACTIONS: Final = "actions"
SECTION_MODES: Final = "modes_limits"
SECTION_ADVANCED: Final = "advanced"
SECTIONS: Final = (SECTION_STATE, SECTION_ACTIONS, SECTION_MODES, SECTION_ADVANCED)

# §3.1 State templates (section "state_templates")
CONF_CURRENT_TEMP_TEMPLATE: Final = "current_temperature_template"
CONF_CURRENT_HUMIDITY_TEMPLATE: Final = "current_humidity_template"
CONF_TARGET_TEMPERATURE_TEMPLATE: Final = "target_temperature_template"
CONF_TARGET_TEMPERATURE_HIGH_TEMPLATE: Final = "target_temperature_high_template"
CONF_TARGET_TEMPERATURE_LOW_TEMPLATE: Final = "target_temperature_low_template"
CONF_TARGET_HUMIDITY_TEMPLATE: Final = "target_humidity_template"
CONF_MIN_HUMIDITY_TEMPLATE: Final = "min_humidity_template"
CONF_MAX_HUMIDITY_TEMPLATE: Final = "max_humidity_template"
CONF_HVAC_MODE_TEMPLATE: Final = "hvac_mode_template"
CONF_HVAC_ACTION_TEMPLATE: Final = "hvac_action_template"
CONF_FAN_MODE_TEMPLATE: Final = "fan_mode_template"
CONF_PRESET_MODE_TEMPLATE: Final = "preset_mode_template"
CONF_SWING_MODE_TEMPLATE: Final = "swing_mode_template"
CONF_TEMP_MIN_TEMPLATE: Final = "min_temp_template"
CONF_TEMP_MAX_TEMPLATE: Final = "max_temp_template"

STATE_TEMPLATE_KEYS: Final = (
    CONF_CURRENT_TEMP_TEMPLATE,
    CONF_CURRENT_HUMIDITY_TEMPLATE,
    CONF_TARGET_TEMPERATURE_TEMPLATE,
    CONF_TARGET_TEMPERATURE_HIGH_TEMPLATE,
    CONF_TARGET_TEMPERATURE_LOW_TEMPLATE,
    CONF_TARGET_HUMIDITY_TEMPLATE,
    CONF_MIN_HUMIDITY_TEMPLATE,
    CONF_MAX_HUMIDITY_TEMPLATE,
    CONF_HVAC_MODE_TEMPLATE,
    CONF_HVAC_ACTION_TEMPLATE,
    CONF_FAN_MODE_TEMPLATE,
    CONF_PRESET_MODE_TEMPLATE,
    CONF_SWING_MODE_TEMPLATE,
    CONF_TEMP_MIN_TEMPLATE,
    CONF_TEMP_MAX_TEMPLATE,
)

# §3.2 Actions (section "actions")
CONF_SET_TEMPERATURE_ACTION: Final = "set_temperature"
CONF_SET_HVAC_MODE_ACTION: Final = "set_hvac_mode"
CONF_SET_FAN_MODE_ACTION: Final = "set_fan_mode"
CONF_SET_PRESET_MODE_ACTION: Final = "set_preset_mode"
CONF_SET_SWING_MODE_ACTION: Final = "set_swing_mode"
CONF_SET_HUMIDITY_ACTION: Final = "set_humidity"

ACTION_KEYS: Final = (
    CONF_SET_TEMPERATURE_ACTION,
    CONF_SET_HVAC_MODE_ACTION,
    CONF_SET_FAN_MODE_ACTION,
    CONF_SET_PRESET_MODE_ACTION,
    CONF_SET_SWING_MODE_ACTION,
    CONF_SET_HUMIDITY_ACTION,
)

# §3.3 Modes and limits (section "modes_limits")
CONF_MODE_LIST: Final = "modes"
CONF_FAN_MODE_LIST: Final = "fan_modes"
CONF_PRESET_MODE_LIST: Final = "preset_modes"
CONF_SWING_MODE_LIST: Final = "swing_modes"
CONF_TEMP_MIN: Final = "min_temp"
CONF_TEMP_MAX: Final = "max_temp"
CONF_PRECISION: Final = "precision"
CONF_TEMP_STEP: Final = "temp_step"

# §3.4 Advanced (section "advanced")
CONF_AVAILABILITY: Final = "availability"
CONF_ICON: Final = "icon"
CONF_PICTURE: Final = "picture"
CONF_ATTRIBUTES: Final = "attributes"
CONF_VARIABLES: Final = "variables"

# ---------------------------------------------------------------------------
# §3.3 Defaults (identical to upstream)
# ---------------------------------------------------------------------------
ALL_HVAC_MODES: Final = [mode.value for mode in HVACMode]
DEFAULT_HVAC_MODES: Final = [
    HVACMode.AUTO.value,
    HVACMode.OFF.value,
    HVACMode.COOL.value,
    HVACMode.HEAT.value,
    HVACMode.DRY.value,
    HVACMode.FAN_ONLY.value,
]
DEFAULT_FAN_MODES: Final = [FAN_AUTO, FAN_LOW, FAN_MEDIUM, FAN_HIGH]
DEFAULT_PRESET_MODES: Final = [
    PRESET_ECO,
    PRESET_AWAY,
    PRESET_BOOST,
    PRESET_COMFORT,
    PRESET_HOME,
    PRESET_SLEEP,
    PRESET_ACTIVITY,
]
DEFAULT_SWING_MODES: Final = [STATE_ON, STATE_OFF]
DEFAULT_TEMP_MIN: Final = float(DEFAULT_MIN_TEMP)
DEFAULT_TEMP_MAX: Final = float(DEFAULT_MAX_TEMP)
DEFAULT_TEMP_STEP: Final = 1.0
# §3.3 Precision is offered as a select; select options must be strings.
PRECISION_OPTIONS: Final = ["0.1", "0.5", "1.0"]

# §4 Optimistic initial values (identical to upstream)
DEFAULT_TARGET_TEMP: Final = 21.0
DEFAULT_FAN_MODE: Final = FAN_LOW
DEFAULT_PRESET_MODE: Final = PRESET_COMFORT
DEFAULT_SWING_MODE: Final = STATE_OFF

# §2.4 Name used for the preview entity when no name is available.
PREVIEW_NAME: Final = "Template Climate preview"
