"""Template Climate UI: template climate entities configured from the UI.

Fork of jcwillox/hass-template-climate (MIT). See SPEC.md for the requirements
referenced (§) throughout the code.
"""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_NAME, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryError

from .const import DOMAIN
from .schema import ClimateConfig, OptionsValidationError, async_parse_options

_LOGGER = logging.getLogger(__name__)

# §1 One config entry creates exactly one climate entity.
PLATFORMS: list[Platform] = [Platform.CLIMATE]

type TemplateClimateConfigEntry = ConfigEntry[ClimateConfig]


async def async_setup_entry(hass: HomeAssistant, entry: TemplateClimateConfigEntry) -> bool:
    """Validate the stored options, then create the climate (§2, §5)."""
    _LOGGER.debug("Setting up '%s' with options %s", entry.title, dict(entry.options))
    try:
        entry.runtime_data = await async_parse_options(
            hass, {**entry.options, CONF_NAME: entry.title}
        )
    except OptionsValidationError as err:
        # §5 ERROR: stored options no longer valid (e.g. an integration used in
        # an action was removed). The user fixes them from the options flow.
        _LOGGER.error("Invalid configuration for '%s': %s", entry.title, err)
        raise ConfigEntryError(
            translation_domain=DOMAIN,
            translation_key="invalid_config",
            translation_placeholders={"name": entry.title, "error": str(err)},
        ) from err

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    _LOGGER.info("Template climate '%s' set up", entry.title)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: TemplateClimateConfigEntry) -> bool:
    """Unload the entry (§2.3: also used by the options-flow reload)."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        _LOGGER.info("Template climate '%s' unloaded", entry.title)
    return unloaded
