"""Form schema and option validation for Template Climate UI.

One module owns the shape of the options (SPEC.md §2-§3) so that the config
flow, the options flow, the live preview and the entity setup all validate
exactly the same way.

Stored options layout (config entry ``options``)::

    {
        "name": "Bedroom aircon",              # §2.1 config flow only
        "device_id": "...",                    # §2.2 optional
        "state_templates": {...},              # §3.1
        "actions": {...},                      # §3.2
        "modes_limits": {...},                 # §3.3
        "advanced": {...},                     # §3.4
    }
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
import logging
from typing import Any

from homeassistant.components.climate import HVACMode
from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import section
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv, selector
from homeassistant.helpers.script import async_validate_actions_config
from homeassistant.helpers.script_variables import ScriptVariables
from homeassistant.helpers.template import Template
import voluptuous as vol

from .const import (
    ACTION_KEYS,
    ALL_HVAC_MODES,
    CONF_ATTRIBUTES,
    CONF_AVAILABILITY,
    CONF_DEVICE_ID,
    CONF_FAN_MODE_LIST,
    CONF_FAN_MODE_TEMPLATE,
    CONF_ICON,
    CONF_MODE_LIST,
    CONF_PICTURE,
    CONF_PRECISION,
    CONF_PRESET_MODE_LIST,
    CONF_PRESET_MODE_TEMPLATE,
    CONF_SET_FAN_MODE_ACTION,
    CONF_SET_PRESET_MODE_ACTION,
    CONF_SET_SWING_MODE_ACTION,
    CONF_SWING_MODE_LIST,
    CONF_SWING_MODE_TEMPLATE,
    CONF_TEMP_MAX,
    CONF_TEMP_MIN,
    CONF_TEMP_STEP,
    CONF_VARIABLES,
    DEFAULT_FAN_MODES,
    DEFAULT_HVAC_MODES,
    DEFAULT_PRESET_MODES,
    DEFAULT_SWING_MODES,
    DEFAULT_TEMP_MAX,
    DEFAULT_TEMP_MIN,
    DEFAULT_TEMP_STEP,
    PRECISION_OPTIONS,
    SECTION_ACTIONS,
    SECTION_ADVANCED,
    SECTION_MODES,
    SECTION_STATE,
    STATE_TEMPLATE_KEYS,
)

_LOGGER = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# §2 Form schema
# ---------------------------------------------------------------------------
def _template_fields(keys: tuple[str, ...]) -> dict[vol.Marker, Any]:
    """Return optional TemplateSelector fields for the given keys (§3.1, §3.4)."""
    return {vol.Optional(key): selector.TemplateSelector() for key in keys}


def _mode_list_selector(options: list[str], translation_key: str) -> selector.SelectSelector:
    """Multi-select with free values, used for fan/preset/swing lists (§3.3)."""
    return selector.SelectSelector(
        selector.SelectSelectorConfig(
            options=options,
            multiple=True,
            custom_value=True,
            mode=selector.SelectSelectorMode.DROPDOWN,
            translation_key=translation_key,
        )
    )


def _temperature_selector() -> selector.NumberSelector:
    """Return a number box for static temperature limits (§3.3)."""
    return selector.NumberSelector(
        selector.NumberSelectorConfig(
            mode=selector.NumberSelectorMode.BOX,
            step=0.1,
        )
    )


def build_schema(*, include_name: bool) -> vol.Schema:
    """Build the single-step form (§2.1 config flow, §2.3 options flow).

    The form is one step split in sections so the live preview (§2.4) always
    receives the complete configuration.
    """
    schema: dict[vol.Marker, Any] = {}
    if include_name:
        # §2.1 The name is asked only on creation; afterwards it is the entry
        # title and can be changed from the entity settings.
        schema[vol.Required(CONF_NAME)] = selector.TextSelector()

    # §2.2 Optional link to an existing device.
    schema[vol.Optional(CONF_DEVICE_ID)] = selector.DeviceSelector()

    # §3.1 State templates.
    schema[vol.Required(SECTION_STATE)] = section(
        vol.Schema(_template_fields(STATE_TEMPLATE_KEYS)),
        {"collapsed": False},
    )

    # §3.2 Actions run on each set_* command.
    schema[vol.Required(SECTION_ACTIONS)] = section(
        vol.Schema({vol.Optional(key): selector.ActionSelector() for key in ACTION_KEYS}),
        {"collapsed": False},
    )

    # §3.3 Mode lists and temperature limits (defaults identical to upstream).
    schema[vol.Required(SECTION_MODES)] = section(
        vol.Schema(
            {
                vol.Required(CONF_MODE_LIST, default=DEFAULT_HVAC_MODES): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=ALL_HVAC_MODES,
                        multiple=True,
                        mode=selector.SelectSelectorMode.DROPDOWN,
                        translation_key="hvac_mode",
                    )
                ),
                vol.Required(CONF_FAN_MODE_LIST, default=DEFAULT_FAN_MODES): _mode_list_selector(
                    DEFAULT_FAN_MODES, "fan_mode"
                ),
                vol.Required(
                    CONF_PRESET_MODE_LIST, default=DEFAULT_PRESET_MODES
                ): _mode_list_selector(DEFAULT_PRESET_MODES, "preset_mode"),
                vol.Required(
                    CONF_SWING_MODE_LIST, default=DEFAULT_SWING_MODES
                ): _mode_list_selector(DEFAULT_SWING_MODES, "swing_mode"),
                vol.Required(CONF_TEMP_MIN, default=DEFAULT_TEMP_MIN): _temperature_selector(),
                vol.Required(CONF_TEMP_MAX, default=DEFAULT_TEMP_MAX): _temperature_selector(),
                vol.Required(CONF_TEMP_STEP, default=DEFAULT_TEMP_STEP): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        mode=selector.NumberSelectorMode.BOX,
                        min=0.01,
                        step=0.01,
                    )
                ),
                vol.Optional(CONF_PRECISION): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=PRECISION_OPTIONS,
                        mode=selector.SelectSelectorMode.DROPDOWN,
                    )
                ),
                # min_temp_template / max_temp_template live in §3.1 next to the
                # other templates; when set they override these static values.
            }
        ),
        {"collapsed": True},
    )

    # §3.4 Availability, icon, picture, extra attributes, script variables.
    schema[vol.Required(SECTION_ADVANCED)] = section(
        vol.Schema(
            {
                **_template_fields((CONF_AVAILABILITY, CONF_ICON, CONF_PICTURE)),
                vol.Optional(CONF_ATTRIBUTES): selector.ObjectSelector(),
                vol.Optional(CONF_VARIABLES): selector.ObjectSelector(),
            }
        ),
        {"collapsed": True},
    )
    return vol.Schema(schema)


# ---------------------------------------------------------------------------
# §2.5 Validation / parsing
# ---------------------------------------------------------------------------
class OptionsValidationError(HomeAssistantError):
    """Invalid options; carries the form section, error key and placeholders."""

    def __init__(self, section_key: str, error: str, field_name: str, detail: str) -> None:
        """Store where the problem is so the flow can point the user to it."""
        super().__init__(f"{section_key}.{field_name}: {error} ({detail})")
        self.section_key = section_key
        self.error = error
        self.placeholders = {"field": field_name, "error": detail}


@dataclass(slots=True)
class ClimateConfig:
    """Validated, ready-to-use configuration of one climate entity (§3)."""

    name: str
    device_id: str | None
    templates: dict[str, Template] = field(default_factory=dict)
    actions: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    hvac_modes: list[HVACMode] = field(default_factory=list)
    fan_modes: list[str] = field(default_factory=list)
    preset_modes: list[str] = field(default_factory=list)
    swing_modes: list[str] = field(default_factory=list)
    min_temp: float = DEFAULT_TEMP_MIN
    max_temp: float = DEFAULT_TEMP_MAX
    temp_step: float = DEFAULT_TEMP_STEP
    precision: float | None = None
    availability: Template | None = None
    icon: Template | None = None
    picture: Template | None = None
    attributes: dict[str, Template] = field(default_factory=dict)
    variables: ScriptVariables | None = None


def _blank(value: Any) -> bool:
    """Return True for values the UI uses to mean "not set"."""
    return value is None or value == "" or value == [] or value == {}


def _parse_template(section_key: str, key: str, value: Any) -> Template:
    """Validate one template string (§2.5 invalid_template)."""
    try:
        return cv.template(value)
    except vol.Invalid as err:
        raise OptionsValidationError(section_key, "invalid_template", key, str(err)) from err


async def async_parse_options(hass: HomeAssistant, options: Mapping[str, Any]) -> ClimateConfig:
    """Validate stored or submitted options and build a ClimateConfig.

    Raises OptionsValidationError on the first problem found (§2.5).
    """
    state = options.get(SECTION_STATE) or {}
    actions = options.get(SECTION_ACTIONS) or {}
    modes = options.get(SECTION_MODES) or {}
    advanced = options.get(SECTION_ADVANCED) or {}

    config = ClimateConfig(
        name=str(options.get(CONF_NAME) or ""),
        device_id=options.get(CONF_DEVICE_ID) or None,
    )

    # §3.1 State templates.
    for key in STATE_TEMPLATE_KEYS:
        if not _blank(value := state.get(key)):
            config.templates[key] = _parse_template(SECTION_STATE, key, value)

    # §3.2 Actions: static schema first, then integration-specific validation
    # (device actions, conditions) exactly as scripts and automations do.
    for key in ACTION_KEYS:
        if _blank(value := actions.get(key)):
            continue
        try:
            sequence = cv.SCRIPT_SCHEMA(value)
            config.actions[key] = await async_validate_actions_config(hass, sequence)
        except (vol.Invalid, HomeAssistantError) as err:
            raise OptionsValidationError(SECTION_ACTIONS, "invalid_action", key, str(err)) from err

    # §3.3 Mode lists.
    hvac_modes = modes.get(CONF_MODE_LIST, DEFAULT_HVAC_MODES)
    if not hvac_modes:
        raise OptionsValidationError(SECTION_MODES, "no_hvac_modes", CONF_MODE_LIST, "")
    try:
        config.hvac_modes = [HVACMode(mode) for mode in hvac_modes]
    except ValueError as err:
        raise OptionsValidationError(
            SECTION_MODES, "invalid_hvac_mode", CONF_MODE_LIST, str(err)
        ) from err

    config.fan_modes = [str(m) for m in modes.get(CONF_FAN_MODE_LIST, DEFAULT_FAN_MODES)]
    config.preset_modes = [str(m) for m in modes.get(CONF_PRESET_MODE_LIST, DEFAULT_PRESET_MODES)]
    config.swing_modes = [str(m) for m in modes.get(CONF_SWING_MODE_LIST, DEFAULT_SWING_MODES)]

    # §3.3 A feature that is configured (template or action) needs a non-empty list.
    for list_key, mode_list, feature_keys in (
        (CONF_FAN_MODE_LIST, config.fan_modes, (CONF_FAN_MODE_TEMPLATE, CONF_SET_FAN_MODE_ACTION)),
        (
            CONF_PRESET_MODE_LIST,
            config.preset_modes,
            (CONF_PRESET_MODE_TEMPLATE, CONF_SET_PRESET_MODE_ACTION),
        ),
        (
            CONF_SWING_MODE_LIST,
            config.swing_modes,
            (CONF_SWING_MODE_TEMPLATE, CONF_SET_SWING_MODE_ACTION),
        ),
    ):
        configured = any(k in config.templates or k in config.actions for k in feature_keys)
        if configured and not mode_list:
            raise OptionsValidationError(SECTION_MODES, "empty_mode_list", list_key, "")

    # §3.3 Temperature limits.
    config.min_temp = float(modes.get(CONF_TEMP_MIN, DEFAULT_TEMP_MIN))
    config.max_temp = float(modes.get(CONF_TEMP_MAX, DEFAULT_TEMP_MAX))
    if config.min_temp >= config.max_temp:
        raise OptionsValidationError(
            SECTION_MODES, "min_max_temp", CONF_TEMP_MIN, f"{config.min_temp} >= {config.max_temp}"
        )
    config.temp_step = float(modes.get(CONF_TEMP_STEP, DEFAULT_TEMP_STEP))
    if not _blank(precision := modes.get(CONF_PRECISION)):
        config.precision = float(precision)

    # §3.4 Advanced.
    for key in (CONF_AVAILABILITY, CONF_ICON, CONF_PICTURE):
        if not _blank(value := advanced.get(key)):
            setattr(config, key, _parse_template(SECTION_ADVANCED, key, value))

    if not _blank(attributes := advanced.get(CONF_ATTRIBUTES)):
        if not isinstance(attributes, Mapping):
            raise OptionsValidationError(
                SECTION_ADVANCED, "invalid_attributes", CONF_ATTRIBUTES, type(attributes).__name__
            )
        for attr_name, attr_template in attributes.items():
            config.attributes[str(attr_name)] = _parse_template(
                SECTION_ADVANCED, f"{CONF_ATTRIBUTES}.{attr_name}", str(attr_template)
            )

    if not _blank(variables := advanced.get(CONF_VARIABLES)):
        try:
            config.variables = cv.SCRIPT_VARIABLES_SCHEMA(variables)
        except vol.Invalid as err:
            raise OptionsValidationError(
                SECTION_ADVANCED, "invalid_variables", CONF_VARIABLES, str(err)
            ) from err

    _LOGGER.debug(
        "Parsed config for '%s': %d templates, %d actions, modes=%s",
        config.name,
        len(config.templates),
        len(config.actions),
        config.hvac_modes,
    )
    return config
