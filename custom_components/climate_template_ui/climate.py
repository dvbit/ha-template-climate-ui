"""Template climate entity configured from the UI.

Behaviour is a port of jcwillox/hass-template-climate (SPEC.md §4); the
template plumbing uses Home Assistant's public tracking helpers instead of the
private internals of the core ``template`` integration, which change often.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
import logging
from typing import Any

from homeassistant.components.climate import (
    ATTR_CURRENT_HUMIDITY,
    ATTR_CURRENT_TEMPERATURE,
    ATTR_FAN_MODE,
    ATTR_HUMIDITY,
    ATTR_HVAC_MODE,
    ATTR_MAX_HUMIDITY,
    ATTR_MAX_TEMP,
    ATTR_MIN_HUMIDITY,
    ATTR_MIN_TEMP,
    ATTR_PRESET_MODE,
    ATTR_SWING_MODE,
    ATTR_TARGET_TEMP_HIGH,
    ATTR_TARGET_TEMP_LOW,
    ENTITY_ID_FORMAT,
    ClimateEntity,
    ClimateEntityFeature,
    HVACAction,
    HVACMode,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    ATTR_TEMPERATURE,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
)
from homeassistant.core import CALLBACK_TYPE, Event, HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError, TemplateError
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.helpers.entity import async_generate_entity_id
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.event import (
    TrackTemplate,
    TrackTemplateResult,
    async_track_template_result,
)
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.script import Script
from homeassistant.helpers.start import async_at_start
from homeassistant.helpers.template import (
    Template,
    TemplateStateFromEntityId,
    result_as_boolean,
)

from .const import (
    CONF_AVAILABILITY,
    CONF_CURRENT_HUMIDITY_TEMPLATE,
    CONF_CURRENT_TEMP_TEMPLATE,
    CONF_FAN_MODE_TEMPLATE,
    CONF_HVAC_ACTION_TEMPLATE,
    CONF_HVAC_MODE_TEMPLATE,
    CONF_ICON,
    CONF_MAX_HUMIDITY_TEMPLATE,
    CONF_MIN_HUMIDITY_TEMPLATE,
    CONF_PICTURE,
    CONF_PRESET_MODE_TEMPLATE,
    CONF_SET_FAN_MODE_ACTION,
    CONF_SET_HUMIDITY_ACTION,
    CONF_SET_HVAC_MODE_ACTION,
    CONF_SET_PRESET_MODE_ACTION,
    CONF_SET_SWING_MODE_ACTION,
    CONF_SET_TEMPERATURE_ACTION,
    CONF_SWING_MODE_TEMPLATE,
    CONF_TARGET_HUMIDITY_TEMPLATE,
    CONF_TARGET_TEMPERATURE_HIGH_TEMPLATE,
    CONF_TARGET_TEMPERATURE_LOW_TEMPLATE,
    CONF_TARGET_TEMPERATURE_TEMPLATE,
    CONF_TEMP_MAX_TEMPLATE,
    CONF_TEMP_MIN_TEMPLATE,
    DEFAULT_FAN_MODE,
    DEFAULT_PRESET_MODE,
    DEFAULT_SWING_MODE,
    DEFAULT_TARGET_TEMP,
    DOMAIN,
    PREVIEW_NAME,
)
from .schema import ClimateConfig

_LOGGER = logging.getLogger(__name__)

# Template results that mean "no data yet": ignored, never logged (§4.2).
_IGNORED_RESULTS = (STATE_UNKNOWN, STATE_UNAVAILABLE, None, "None", "")

type PreviewCallback = Callable[[str | None, Mapping[str, Any] | None, str | None], None]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry[ClimateConfig],
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Create the climate entity of one config entry (§2, one entry = one climate).

    Options were already validated in __init__.async_setup_entry (runtime_data).
    """
    async_add_entities([TemplateClimate(hass, entry.runtime_data, unique_id=entry.entry_id)])


def async_create_preview_climate(
    hass: HomeAssistant, config: ClimateConfig, entity_id: str | None
) -> TemplateClimate:
    """Build an unregistered entity used by the flow preview (§2.4)."""
    entity = TemplateClimate(hass, config, unique_id=None)
    entity.hass = hass
    entity.entity_id = entity_id or async_generate_entity_id(
        ENTITY_ID_FORMAT, config.name or PREVIEW_NAME, hass=hass
    )
    return entity


class TemplateClimate(ClimateEntity, RestoreEntity):
    """Climate entity driven by templates and actions (§4)."""

    _attr_should_poll = False

    def __init__(self, hass: HomeAssistant, config: ClimateConfig, unique_id: str | None) -> None:
        """Initialise from a validated ClimateConfig."""
        self._config = config
        self._attr_unique_id = unique_id
        self._attr_name = config.name or PREVIEW_NAME

        # §2.2 Link to an existing device; composite devices are not allowed,
        # same rule as the core template helpers.
        if config.device_id and (
            device := dr.async_get(hass).async_get(
                config.device_id, include_composite_devices=False
            )
        ):
            self.device_entry = device

        # §3.3 Static attributes.
        self._attr_temperature_unit = hass.config.units.temperature_unit
        self._attr_hvac_modes = list(config.hvac_modes)
        self._attr_fan_modes = list(config.fan_modes)
        self._attr_preset_modes = list(config.preset_modes)
        self._attr_swing_modes = list(config.swing_modes)
        self._attr_min_temp = config.min_temp
        self._attr_max_temp = config.max_temp
        self._attr_target_temperature_step = config.temp_step
        if config.precision is not None:
            self._attr_precision = config.precision

        # §4.1 Optimistic defaults (identical to upstream).
        self._attr_hvac_mode = HVACMode.OFF if HVACMode.OFF in config.hvac_modes else None
        self._attr_fan_mode = DEFAULT_FAN_MODE
        self._attr_preset_mode = DEFAULT_PRESET_MODE
        self._attr_swing_mode = DEFAULT_SWING_MODE
        self._attr_target_temperature = DEFAULT_TARGET_TEMP
        self._attr_target_temperature_high = None
        self._attr_target_temperature_low = None
        self._attr_hvac_action = None
        self._attr_extra_state_attributes = {}

        # §3.2 One Script per configured action.
        self._scripts: dict[str, Script] = {
            key: Script(hass, sequence, f"{self._attr_name} {key}", DOMAIN)
            for key, sequence in config.actions.items()
        }

        self._attr_supported_features = self._compute_features()
        self._preview_callback: PreviewCallback | None = None
        self._preview_unsubs: list[CALLBACK_TYPE] = []

    # ------------------------------------------------------------------
    # §4.3 Supported features
    # ------------------------------------------------------------------
    def _has(self, template_key: str | None, action_key: str | None) -> bool:
        """Return True if a template or an action configures a feature."""
        return (template_key is not None and template_key in self._config.templates) or (
            action_key is not None and action_key in self._config.actions
        )

    def _compute_features(self) -> ClimateEntityFeature:
        """Feature bits: a feature exists when its template or action exists."""
        features = ClimateEntityFeature(0)
        modes = self._attr_hvac_modes

        # TURN_ON / TURN_OFF: same rule as upstream.
        if len(modes) >= 2:
            features |= ClimateEntityFeature.TURN_ON
        if HVACMode.OFF in modes or len(modes) > 1:
            features |= ClimateEntityFeature.TURN_OFF

        if self._has(CONF_TARGET_HUMIDITY_TEMPLATE, CONF_SET_HUMIDITY_ACTION):
            features |= ClimateEntityFeature.TARGET_HUMIDITY
        if self._has(CONF_FAN_MODE_TEMPLATE, CONF_SET_FAN_MODE_ACTION):
            features |= ClimateEntityFeature.FAN_MODE
        if self._has(CONF_PRESET_MODE_TEMPLATE, CONF_SET_PRESET_MODE_ACTION):
            features |= ClimateEntityFeature.PRESET_MODE
        if self._has(CONF_SWING_MODE_TEMPLATE, CONF_SET_SWING_MODE_ACTION):
            features |= ClimateEntityFeature.SWING_MODE

        has_temperature = any(
            self._has(key, None)
            for key in (
                CONF_TARGET_TEMPERATURE_TEMPLATE,
                CONF_TARGET_TEMPERATURE_HIGH_TEMPLATE,
                CONF_TARGET_TEMPERATURE_LOW_TEMPLATE,
            )
        ) or self._has(None, CONF_SET_TEMPERATURE_ACTION)
        if has_temperature:
            # Range only with heat_cool; single target unless heat_cool (+off)
            # is the only mode — upstream logic.
            if HVACMode.HEAT_COOL in modes:
                features |= ClimateEntityFeature.TARGET_TEMPERATURE_RANGE
                others = [m for m in modes if m not in (HVACMode.HEAT_COOL, HVACMode.OFF)]
                if others:
                    features |= ClimateEntityFeature.TARGET_TEMPERATURE
            else:
                features |= ClimateEntityFeature.TARGET_TEMPERATURE
        return features

    # ------------------------------------------------------------------
    # §4.4 Lifecycle: restore, then track templates once HA is running
    # ------------------------------------------------------------------
    async def async_added_to_hass(self) -> None:
        """Restore the last state and start template tracking."""
        await super().async_added_to_hass()
        await self._async_restore()
        self.async_on_remove(async_at_start(self.hass, self._async_at_start))
        _LOGGER.info(
            "Climate '%s' ready (%s): %d templates, actions=%s",
            self._attr_name,
            self.entity_id,
            len(self._config.templates),
            list(self._scripts) or "none (optimistic)",
        )

    async def async_will_remove_from_hass(self) -> None:
        """Stop running actions when the entity goes away."""
        for script in self._scripts.values():
            await script.async_stop()
        await super().async_will_remove_from_hass()

    async def _async_restore(self) -> None:
        """§4.4 Restore optimistic values from the last known state (upstream rules)."""
        if (last := await self.async_get_last_state()) is None:
            _LOGGER.debug("%s: no previous state to restore", self.entity_id)
            return
        attrs = last.attributes
        if CONF_TEMP_MIN_TEMPLATE in self._config.templates and attrs.get(ATTR_MIN_TEMP):
            self._attr_min_temp = float(attrs[ATTR_MIN_TEMP])
        if CONF_TEMP_MAX_TEMPLATE in self._config.templates and attrs.get(ATTR_MAX_TEMP):
            self._attr_max_temp = float(attrs[ATTR_MAX_TEMP])
        if last.state in self._attr_hvac_modes:
            self._attr_hvac_mode = HVACMode(last.state)
        if (temperature := attrs.get(ATTR_TEMPERATURE)) is not None:
            self._attr_target_temperature = float(temperature)
        if (high := attrs.get(ATTR_TARGET_TEMP_HIGH)) is not None:
            self._attr_target_temperature_high = float(high)
        if (low := attrs.get(ATTR_TARGET_TEMP_LOW)) is not None:
            self._attr_target_temperature_low = float(low)
        self._attr_fan_mode = attrs.get(ATTR_FAN_MODE, DEFAULT_FAN_MODE)
        self._attr_preset_mode = attrs.get(ATTR_PRESET_MODE, DEFAULT_PRESET_MODE)
        self._attr_swing_mode = attrs.get(ATTR_SWING_MODE, DEFAULT_SWING_MODE)
        if (current := attrs.get(ATTR_CURRENT_TEMPERATURE)) is not None:
            self._attr_current_temperature = float(current)
        if (humidity := attrs.get(ATTR_CURRENT_HUMIDITY)) is not None:
            self._attr_current_humidity = humidity
        if (humidity := attrs.get(ATTR_MIN_HUMIDITY)) is not None:
            self._attr_min_humidity = humidity
        if (humidity := attrs.get(ATTR_MAX_HUMIDITY)) is not None:
            self._attr_max_humidity = humidity
        if (humidity := attrs.get(ATTR_HUMIDITY)) is not None:
            self._attr_target_humidity = humidity
        _LOGGER.debug("%s: restored state %s", self.entity_id, last.state)

    @callback
    def _async_at_start(self, _hass: HomeAssistant | None = None) -> None:
        """Start tracking for the registered entity."""
        self.async_on_remove(self._async_start_tracking())

    # ------------------------------------------------------------------
    # §4.2 Template tracking
    # ------------------------------------------------------------------
    def _handlers(self) -> dict[str, Callable[[Any], None]]:
        """Map each configured template key to its result handler."""
        return {
            CONF_TEMP_MIN_TEMPLATE: self._update_min_temp,
            CONF_TEMP_MAX_TEMPLATE: self._update_max_temp,
            CONF_CURRENT_TEMP_TEMPLATE: self._update_current_temp,
            CONF_CURRENT_HUMIDITY_TEMPLATE: self._update_current_humidity,
            CONF_MIN_HUMIDITY_TEMPLATE: self._update_min_humidity,
            CONF_MAX_HUMIDITY_TEMPLATE: self._update_max_humidity,
            CONF_TARGET_HUMIDITY_TEMPLATE: self._update_target_humidity,
            CONF_TARGET_TEMPERATURE_TEMPLATE: self._update_target_temp,
            CONF_TARGET_TEMPERATURE_HIGH_TEMPLATE: self._update_target_temp_high,
            CONF_TARGET_TEMPERATURE_LOW_TEMPLATE: self._update_target_temp_low,
            CONF_HVAC_MODE_TEMPLATE: self._update_hvac_mode,
            CONF_HVAC_ACTION_TEMPLATE: self._update_hvac_action,
            CONF_FAN_MODE_TEMPLATE: self._update_fan_mode,
            CONF_PRESET_MODE_TEMPLATE: self._update_preset_mode,
            CONF_SWING_MODE_TEMPLATE: self._update_swing_mode,
        }

    def _template_variables(self) -> dict[str, Any]:
        """Variables for templates and actions: `this` plus configured variables (§3.4)."""
        variables: dict[str, Any] = {"this": TemplateStateFromEntityId(self.hass, self.entity_id)}
        if self._config.variables is not None:
            variables = self._config.variables.async_render(self.hass, variables)
        return variables

    @callback
    def _async_start_tracking(self) -> CALLBACK_TYPE:
        """Track every template with a single listener; return the unsubscribe."""
        # Several keys may share an identical template string: Template objects
        # compare by text, so group handlers per template.
        handlers_by_template: dict[Template, list[tuple[str, Callable[[Any], None]]]] = {}
        all_handlers = self._handlers()
        for key, template in self._config.templates.items():
            handlers_by_template.setdefault(template, []).append((key, all_handlers[key]))
        for key, template, handler in (
            (CONF_AVAILABILITY, self._config.availability, self._update_availability),
            (CONF_ICON, self._config.icon, self._update_icon),
            (CONF_PICTURE, self._config.picture, self._update_picture),
        ):
            if template is not None:
                handlers_by_template.setdefault(template, []).append((key, handler))
        for attr_name, template in self._config.attributes.items():
            handlers_by_template.setdefault(template, []).append(
                (f"attributes.{attr_name}", self._attribute_updater(attr_name))
            )

        if not handlers_by_template:
            _LOGGER.debug("%s: no templates, fully optimistic", self.entity_id)
            self._async_publish(None)
            return lambda: None

        variables = self._template_variables()

        @callback
        def _on_results(event: Event | None, updates: list[TrackTemplateResult]) -> None:
            error: str | None = None
            for update in updates:
                for key, handler in handlers_by_template.get(update.template, []):
                    if isinstance(update.result, TemplateError):
                        # §5 WARNING: the template failed to render.
                        _LOGGER.warning(
                            "%s: template '%s' failed: %s", self.entity_id, key, update.result
                        )
                        error = f"{key}: {update.result}"
                        handler(None)
                        continue
                    _LOGGER.debug("%s: %s -> %r", self.entity_id, key, update.result)
                    handler(update.result)
            self._async_publish(error)

        info = async_track_template_result(
            self.hass,
            [TrackTemplate(template, variables) for template in handlers_by_template],
            _on_results,
        )
        info.async_refresh()
        _LOGGER.debug("%s: tracking %d templates", self.entity_id, len(handlers_by_template))
        return info.async_remove

    @callback
    def _async_publish(self, error: str | None) -> None:
        """Write state, or feed the preview when running inside a flow (§2.4)."""
        if self._preview_callback is None:
            self.async_write_ha_state()
            return
        try:
            calculated = self._async_calculate_state()
        except Exception as err:  # noqa: BLE001 - surfaced to the preview UI
            self._preview_callback(None, None, str(err))
            return
        self._preview_callback(calculated.state, calculated.attributes, error)

    @callback
    def async_start_preview(self, preview_callback: PreviewCallback) -> CALLBACK_TYPE:
        """Run the entity detached from the registry for the flow preview (§2.4)."""
        self._preview_callback = preview_callback
        unsub = self._async_start_tracking()
        _LOGGER.debug("Preview started for '%s'", self._attr_name)
        return unsub

    # ------------------------------------------------------------------
    # §4.2 Result handlers (semantics identical to upstream; parse errors are
    # WARNING because they come from user data, not from this code)
    # ------------------------------------------------------------------
    def _to_float(self, key: str, value: Any) -> float | None:
        """Parse a numeric template result, ignoring unknown/unavailable."""
        if value in _IGNORED_RESULTS:
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            _LOGGER.warning("%s: '%s' is not a number: %r", self.entity_id, key, value)
            return None

    def _update_min_temp(self, value: Any) -> None:
        if (parsed := self._to_float(CONF_TEMP_MIN_TEMPLATE, value)) is not None:
            self._attr_min_temp = parsed

    def _update_max_temp(self, value: Any) -> None:
        if (parsed := self._to_float(CONF_TEMP_MAX_TEMPLATE, value)) is not None:
            self._attr_max_temp = parsed

    def _update_current_temp(self, value: Any) -> None:
        if (parsed := self._to_float(CONF_CURRENT_TEMP_TEMPLATE, value)) is not None:
            self._attr_current_temperature = parsed

    def _update_current_humidity(self, value: Any) -> None:
        if (parsed := self._to_float(CONF_CURRENT_HUMIDITY_TEMPLATE, value)) is not None:
            self._attr_current_humidity = parsed

    def _update_min_humidity(self, value: Any) -> None:
        if (parsed := self._to_float(CONF_MIN_HUMIDITY_TEMPLATE, value)) is not None:
            self._attr_min_humidity = parsed

    def _update_max_humidity(self, value: Any) -> None:
        if (parsed := self._to_float(CONF_MAX_HUMIDITY_TEMPLATE, value)) is not None:
            self._attr_max_humidity = parsed

    def _update_target_humidity(self, value: Any) -> None:
        if (parsed := self._to_float(CONF_TARGET_HUMIDITY_TEMPLATE, value)) is not None:
            self._attr_target_humidity = parsed

    def _update_target_temp(self, value: Any) -> None:
        if (parsed := self._to_float(CONF_TARGET_TEMPERATURE_TEMPLATE, value)) is not None:
            self._attr_target_temperature = parsed

    def _update_target_temp_high(self, value: Any) -> None:
        if (parsed := self._to_float(CONF_TARGET_TEMPERATURE_HIGH_TEMPLATE, value)) is not None:
            self._attr_target_temperature_high = parsed

    def _update_target_temp_low(self, value: Any) -> None:
        if (parsed := self._to_float(CONF_TARGET_TEMPERATURE_LOW_TEMPLATE, value)) is not None:
            self._attr_target_temperature_low = parsed

    def _update_mode(self, key: str, value: Any, allowed: list[str], attr: str) -> None:
        """Accept a mode only if it is in the configured list (§4.2)."""
        if value in _IGNORED_RESULTS:
            return
        text = str(value)
        if text in allowed:
            setattr(self, attr, text)
        else:
            _LOGGER.warning(
                "%s: '%s' returned %r, expected one of %s", self.entity_id, key, value, allowed
            )

    def _update_hvac_mode(self, value: Any) -> None:
        if value in _IGNORED_RESULTS:
            return
        if str(value) in self._attr_hvac_modes:
            self._attr_hvac_mode = HVACMode(str(value))
        else:
            _LOGGER.warning(
                "%s: '%s' returned %r, expected one of %s",
                self.entity_id,
                CONF_HVAC_MODE_TEMPLATE,
                value,
                [str(m) for m in self._attr_hvac_modes],
            )

    def _update_fan_mode(self, value: Any) -> None:
        self._update_mode(CONF_FAN_MODE_TEMPLATE, value, self._attr_fan_modes, "_attr_fan_mode")

    def _update_preset_mode(self, value: Any) -> None:
        self._update_mode(
            CONF_PRESET_MODE_TEMPLATE, value, self._attr_preset_modes, "_attr_preset_mode"
        )

    def _update_swing_mode(self, value: Any) -> None:
        self._update_mode(
            CONF_SWING_MODE_TEMPLATE, value, self._attr_swing_modes, "_attr_swing_mode"
        )

    def _update_hvac_action(self, value: Any) -> None:
        if value in (None, "", "None"):
            self._attr_hvac_action = None
            return
        if value in (STATE_UNKNOWN, STATE_UNAVAILABLE):
            return
        try:
            self._attr_hvac_action = HVACAction(str(value))
        except ValueError:
            _LOGGER.warning(
                "%s: '%s' returned %r, expected one of %s",
                self.entity_id,
                CONF_HVAC_ACTION_TEMPLATE,
                value,
                [a.value for a in HVACAction],
            )

    def _update_availability(self, value: Any) -> None:
        # §3.4 Only a true result makes the entity available; errors → unavailable.
        self._attr_available = value is not None and result_as_boolean(value)

    def _update_icon(self, value: Any) -> None:
        self._attr_icon = None if value in _IGNORED_RESULTS else str(value)

    def _update_picture(self, value: Any) -> None:
        self._attr_entity_picture = None if value in _IGNORED_RESULTS else str(value)

    def _attribute_updater(self, name: str) -> Callable[[Any], None]:
        """Return a handler storing one extra attribute (§3.4)."""

        def _update(value: Any) -> None:
            self._attr_extra_state_attributes = {
                **self._attr_extra_state_attributes,
                name: value,
            }

        return _update

    # ------------------------------------------------------------------
    # §4.1 Target temperature visibility depends on heat_cool (upstream)
    # ------------------------------------------------------------------
    @property
    def target_temperature(self) -> float | None:
        """Single target, hidden while in heat_cool."""
        if self._attr_hvac_mode == HVACMode.HEAT_COOL:
            return None
        return self._attr_target_temperature

    @property
    def target_temperature_high(self) -> float | None:
        """Upper target, only in heat_cool."""
        if self._attr_hvac_mode != HVACMode.HEAT_COOL:
            return None
        return self._attr_target_temperature_high

    @property
    def target_temperature_low(self) -> float | None:
        """Lower target, only in heat_cool."""
        if self._attr_hvac_mode != HVACMode.HEAT_COOL:
            return None
        return self._attr_target_temperature_low

    # ------------------------------------------------------------------
    # §4.5 Commands: optimistic update when no template, then run the action
    # ------------------------------------------------------------------
    async def _async_run(self, key: str, variables: dict[str, Any]) -> None:
        """Run the configured action for `key`, if any."""
        if (script := self._scripts.get(key)) is None:
            _LOGGER.debug("%s: no '%s' action, optimistic only", self.entity_id, key)
            return
        run_variables = {**self._template_variables(), **variables}
        _LOGGER.info("%s: running '%s' with %s", self.entity_id, key, variables)
        try:
            await script.async_run(run_variables, context=self._context)
        except HomeAssistantError as err:
            # §5 ERROR: the user's action failed; re-raise so the caller sees it.
            _LOGGER.error("%s: action '%s' failed: %s", self.entity_id, key, err)
            raise

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        """Set the HVAC mode."""
        if CONF_HVAC_MODE_TEMPLATE not in self._config.templates:
            self._attr_hvac_mode = hvac_mode
            self.async_write_ha_state()
        await self._async_run(CONF_SET_HVAC_MODE_ACTION, {ATTR_HVAC_MODE: hvac_mode})

    async def async_set_preset_mode(self, preset_mode: str) -> None:
        """Set the preset."""
        if CONF_PRESET_MODE_TEMPLATE not in self._config.templates:
            self._attr_preset_mode = preset_mode
            self.async_write_ha_state()
        await self._async_run(CONF_SET_PRESET_MODE_ACTION, {ATTR_PRESET_MODE: preset_mode})

    async def async_set_fan_mode(self, fan_mode: str) -> None:
        """Set the fan mode."""
        if CONF_FAN_MODE_TEMPLATE not in self._config.templates:
            self._attr_fan_mode = fan_mode
            self.async_write_ha_state()
        await self._async_run(CONF_SET_FAN_MODE_ACTION, {ATTR_FAN_MODE: fan_mode})

    async def async_set_swing_mode(self, swing_mode: str) -> None:
        """Set the swing mode."""
        if CONF_SWING_MODE_TEMPLATE not in self._config.templates:
            self._attr_swing_mode = swing_mode
            self.async_write_ha_state()
        await self._async_run(CONF_SET_SWING_MODE_ACTION, {ATTR_SWING_MODE: swing_mode})

    async def async_set_humidity(self, humidity: int) -> None:
        """Set the target humidity."""
        if CONF_TARGET_HUMIDITY_TEMPLATE not in self._config.templates:
            self._attr_target_humidity = humidity
            self.async_write_ha_state()
        await self._async_run(CONF_SET_HUMIDITY_ACTION, {ATTR_HUMIDITY: humidity})

    async def async_set_temperature(self, **kwargs: Any) -> None:
        """Set target temperature(s), optionally changing mode (upstream logic)."""
        mode = kwargs.get(ATTR_HVAC_MODE, self._attr_hvac_mode)
        updated = False
        if mode == HVACMode.HEAT_COOL:
            for attr, key, template_key in (
                (
                    "_attr_target_temperature_high",
                    ATTR_TARGET_TEMP_HIGH,
                    CONF_TARGET_TEMPERATURE_HIGH_TEMPLATE,
                ),
                (
                    "_attr_target_temperature_low",
                    ATTR_TARGET_TEMP_LOW,
                    CONF_TARGET_TEMPERATURE_LOW_TEMPLATE,
                ),
            ):
                value = kwargs.get(key)
                if value is not None and template_key not in self._config.templates:
                    setattr(self, attr, value)
                    updated = True
        elif (
            value := kwargs.get(ATTR_TEMPERATURE)
        ) is not None and CONF_TARGET_TEMPERATURE_TEMPLATE not in self._config.templates:
            self._attr_target_temperature = value
            updated = True
        if updated:
            self.async_write_ha_state()

        if (new_mode := kwargs.get(ATTR_HVAC_MODE)) and HVACMode(new_mode) != self._attr_hvac_mode:
            await self.async_set_hvac_mode(HVACMode(new_mode))

        await self._async_run(
            CONF_SET_TEMPERATURE_ACTION,
            {
                ATTR_TEMPERATURE: kwargs.get(ATTR_TEMPERATURE),
                ATTR_TARGET_TEMP_HIGH: kwargs.get(ATTR_TARGET_TEMP_HIGH),
                ATTR_TARGET_TEMP_LOW: kwargs.get(ATTR_TARGET_TEMP_LOW),
                ATTR_HVAC_MODE: kwargs.get(ATTR_HVAC_MODE),
            },
        )

    async def async_turn_on(self) -> None:
        """Turn on; fall back to the first non-off mode if HA cannot pick one (§4.5)."""
        try:
            await super().async_turn_on()
        except NotImplementedError:
            target = next((m for m in self._attr_hvac_modes if m != HVACMode.OFF), None)
            if target is None:
                raise
            await self.async_set_hvac_mode(target)


def async_find_entity_id(hass: HomeAssistant, entry_id: str) -> str | None:
    """Entity id of an entry's climate, used by the options-flow preview (§2.4)."""
    return er.async_get(hass).async_get_entity_id("climate", DOMAIN, entry_id)
