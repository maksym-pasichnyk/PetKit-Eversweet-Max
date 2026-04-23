"""Select platform for CTW3 mode selection."""
from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, MODE_NAMES, MODE_OPTION_ALIASES, MODES
from .coordinator import CTW3Coordinator
from .entity import CTW3Entity

OPTIONS = list(MODE_NAMES.keys())


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: CTW3Coordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([CTW3ModeSelect(coordinator)])


class CTW3ModeSelect(CTW3Entity, SelectEntity):
    _attr_translation_key = "mode"
    _attr_icon = "mdi:flash"
    _attr_options = OPTIONS

    def __init__(self, coordinator: CTW3Coordinator) -> None:
        super().__init__(coordinator, key="mode_select")

    @property
    def current_option(self) -> str | None:
        state = self.coordinator.data
        if state is None or state.running is None:
            return None
        return MODES.get(state.running.mode)

    async def async_select_option(self, option: str) -> None:
        code = MODE_NAMES.get(option)
        if code is None:
            code = MODE_OPTION_ALIASES.get(option)
        if code is None:
            raise ValueError(f"unknown mode {option}")
        await self.coordinator.async_set_mode(code)
