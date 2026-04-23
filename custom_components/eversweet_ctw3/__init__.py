"""PetKit Eversweet Max Smart (CTW3) integration for Home Assistant."""
from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_ADDRESS, Platform
from homeassistant.core import HomeAssistant

from .const import CONF_NAME, CONF_SECRET, DOMAIN
from .coordinator import CTW3Coordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [
    Platform.SENSOR,
    Platform.BINARY_SENSOR,
    Platform.SWITCH,
    Platform.SELECT,
    Platform.BUTTON,
    Platform.NUMBER,
]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up CTW3 from a config entry."""
    address: str = entry.data[CONF_ADDRESS]
    secret_hex: str = entry.data[CONF_SECRET]
    name: str = entry.data.get(CONF_NAME, "CTW3")

    try:
        secret = bytes.fromhex(secret_hex)
    except ValueError as err:
        _LOGGER.error("Invalid secret in config entry: %s", err)
        return False
    if len(secret) != 8:
        _LOGGER.error("Secret must be 8 bytes (16 hex chars), got %d", len(secret))
        return False

    coordinator = CTW3Coordinator(
        hass,
        address=address,
        secret=secret,
        name=name,
    )
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Register services on first setup only
    from .services import async_register_services

    async_register_services(hass)

    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        coordinator: CTW3Coordinator = hass.data[DOMAIN].pop(entry.entry_id)
        await coordinator.async_shutdown()
    return unload_ok


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)
