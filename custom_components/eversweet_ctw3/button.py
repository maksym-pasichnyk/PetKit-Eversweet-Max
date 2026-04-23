"""Button platform for CTW3 (reset filter, sync history)."""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from homeassistant.components.button import (
    ButtonDeviceClass,
    ButtonEntity,
    ButtonEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import CTW3Coordinator
from .entity import CTW3Entity


@dataclass(frozen=True, kw_only=True)
class CTW3ButtonEntityDescription(ButtonEntityDescription):
    press_fn: Callable[[CTW3Coordinator], Awaitable[None]]


BUTTONS: tuple[CTW3ButtonEntityDescription, ...] = (
    CTW3ButtonEntityDescription(
        key="reset_filter",
        translation_key="reset_filter",
        icon="mdi:air-filter",
        device_class=ButtonDeviceClass.RESTART,
        entity_category=EntityCategory.CONFIG,
        press_fn=lambda c: c.async_reset_filter(),
    ),
    CTW3ButtonEntityDescription(
        key="sync_history",
        translation_key="sync_history",
        icon="mdi:history",
        entity_category=EntityCategory.DIAGNOSTIC,
        press_fn=lambda c: c.async_sync_history(),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: CTW3Coordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(CTW3Button(coordinator, d) for d in BUTTONS)


class CTW3Button(CTW3Entity, ButtonEntity):
    entity_description: CTW3ButtonEntityDescription

    def __init__(
        self,
        coordinator: CTW3Coordinator,
        description: CTW3ButtonEntityDescription,
    ) -> None:
        super().__init__(coordinator, key=description.key)
        self.entity_description = description

    async def async_press(self) -> None:
        await self.entity_description.press_fn(self.coordinator)
