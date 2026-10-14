"""Config and options flow for Template Climate UI (SPEC.md §2)."""

from __future__ import annotations

from collections.abc import Mapping
import logging
from typing import Any

from homeassistant.components import websocket_api
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlowWithReload,
)
from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
import voluptuous as vol

from .climate import async_create_preview_climate, async_find_entity_id
from .const import DOMAIN
from .schema import OptionsValidationError, async_parse_options, build_schema

_LOGGER = logging.getLogger(__name__)


async def _async_validate(
    hass: HomeAssistant, user_input: Mapping[str, Any]
) -> tuple[dict[str, str], dict[str, str]]:
    """Validate a submitted form; return (errors, description placeholders) (§2.5).

    Errors are keyed by section so the frontend shows them above the section
    that contains the faulty field; the field name and the parser message are
    passed as placeholders.
    """
    try:
        await async_parse_options(hass, user_input)
    except OptionsValidationError as err:
        _LOGGER.warning("Rejected configuration: %s", err)
        return {err.section_key: err.error}, err.placeholders
    return {}, {}


class TemplateClimateConfigFlow(ConfigFlow, domain=DOMAIN):
    """§2.1 Create one template climate per config entry."""

    VERSION = 1
    MINOR_VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Single step with sections and live preview."""
        errors: dict[str, str] = {}
        placeholders: dict[str, str] = {"field": "", "error": ""}
        if user_input is not None:
            errors, found = await _async_validate(self.hass, user_input)
            placeholders.update(found)
            if not errors:
                name = user_input[CONF_NAME]
                _LOGGER.info("Creating template climate '%s'", name)
                # §2.1 Everything lives in options (core helper convention), so
                # the options flow can edit it without touching entry data.
                return self.async_create_entry(title=name, data={}, options=user_input)

        schema = build_schema(include_name=True)
        if user_input is not None:
            # Keep what the user typed when the form is shown again with errors.
            schema = self.add_suggested_values_to_schema(schema, user_input)
        return self.async_show_form(
            step_id="user",
            data_schema=schema,
            errors=errors,
            description_placeholders=placeholders,
            preview=DOMAIN,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> TemplateClimateOptionsFlow:
        """§2.3 Options flow; never pass config_entry to the constructor."""
        return TemplateClimateOptionsFlow()

    @staticmethod
    async def async_setup_preview(hass: HomeAssistant) -> None:
        """§2.4 Register the preview websocket command."""
        websocket_api.async_register_command(hass, ws_start_preview)


class TemplateClimateOptionsFlow(OptionsFlowWithReload):
    """§2.3 Edit every field after creation; the entry reloads on save."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Show the config-flow form without the name."""
        errors: dict[str, str] = {}
        placeholders: dict[str, str] = {"field": "", "error": ""}
        if user_input is not None:
            errors, found = await _async_validate(
                self.hass, {**user_input, CONF_NAME: self.config_entry.title}
            )
            placeholders.update(found)
            if not errors:
                _LOGGER.info("Options updated for '%s'", self.config_entry.title)
                return self.async_create_entry(
                    data={**user_input, CONF_NAME: self.config_entry.title}
                )

        current = user_input if user_input is not None else self.config_entry.options
        return self.async_show_form(
            step_id="init",
            data_schema=self.add_suggested_values_to_schema(
                build_schema(include_name=False), current
            ),
            errors=errors,
            description_placeholders=placeholders,
            preview=DOMAIN,
        )

    @staticmethod
    async def async_setup_preview(hass: HomeAssistant) -> None:
        """§2.4 Register the preview websocket command."""
        websocket_api.async_register_command(hass, ws_start_preview)


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/start_preview",
        vol.Required("flow_id"): str,
        vol.Required("flow_type"): vol.Any("config_flow", "options_flow"),
        vol.Required("user_input"): dict,
    }
)
@websocket_api.async_response
async def ws_start_preview(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """§2.4 Render the climate state live while the form is being edited.

    Protocol of the frontend generic preview: events carry `state` and
    `attributes`, or `error`; `domain` tells the UI which entity row to draw.
    """
    user_input: dict[str, Any] = dict(msg["user_input"])
    entity_id: str | None = None
    if msg["flow_type"] == "options_flow":
        flow_status = hass.config_entries.options.async_get(msg["flow_id"])
        entry = hass.config_entries.async_get_entry(flow_status["handler"])
        if entry is None:
            raise HomeAssistantError("Config entry not found")
        user_input[CONF_NAME] = entry.title
        entity_id = async_find_entity_id(hass, entry.entry_id)

    @callback
    def _send(state: str | None, attributes: Mapping[str, Any] | None, error: str | None) -> None:
        payload: dict[str, Any] = {"domain": "climate"}
        if error is not None or state is None:
            # A failing template is shown instead of a misleading state.
            payload["error"] = error or "Preview not ready"
        else:
            payload |= {"state": state, "attributes": dict(attributes or {})}
        connection.send_message(websocket_api.event_message(msg["id"], payload))

    try:
        config = await async_parse_options(hass, user_input)
    except OptionsValidationError as err:
        # Show the problem in the preview box instead of failing the subscription.
        connection.send_result(msg["id"])
        _send(None, None, str(err))
        connection.subscriptions[msg["id"]] = lambda: None
        return

    preview = async_create_preview_climate(hass, config, entity_id)
    connection.send_result(msg["id"])
    connection.subscriptions[msg["id"]] = preview.async_start_preview(_send)
