"""Select platform for CTW3 mode and lamp-ring selection."""
from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, MODE_NAMES, MODE_OPTION_ALIASES, MODES
from .coordinator import CTW3Coordinator
from .entity import CTW3Entity

OPTIONS = list(MODE_NAMES.keys())

# Lamp brightness levels: option name → device percentage (0-100)
LAMP_LEVELS: dict[str, int | None] = {
    "off":    None,   # disabled
    "low":    25,
    "medium": 60,
    "high":   100,
}
LAMP_OPTIONS = list(LAMP_LEVELS.keys())


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: CTW3Coordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([CTW3ModeSelect(coordinator), CTW3LampSelect(coordinator)])


class CTW3ModeSelect(CTW3Entity, SelectEntity):
    _attr_translation_key = "mode"
    _attr_icon = "mdi:water-sync"
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


class CTW3LampSelect(CTW3Entity, SelectEntity):
    """Lamp-ring select — off / low / medium / high."""

    _attr_translation_key = "lamp_ring"
    _attr_icon = "mdi:lightbulb-on"
    _attr_options = LAMP_OPTIONS

    def __init__(self, coordinator: CTW3Coordinator) -> None:
        super().__init__(coordinator, key="lamp_ring")

    @property
    def current_option(self) -> str | None:
        state = self.coordinator.data
        if state is None or state.settings is None:
            return None
        if not state.settings.lamp_ring_switch:
            return "off"
        pct = state.settings.lamp_ring_brightness or 0
        if pct <= 40:
            return "low"
        if pct <= 75:
            return "medium"
        return "high"

    async def async_select_option(self, option: str) -> None:
        if option not in LAMP_LEVELS:
            raise ValueError(f"unknown lamp level: {option}")
        brightness = LAMP_LEVELS[option]
        if brightness is None:
            await self.coordinator.async_set_lamp_ring(enabled=False)
        else:
            await self.coordinator.async_set_lamp_ring(enabled=True, brightness=brightness)
