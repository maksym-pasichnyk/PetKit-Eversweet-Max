"""Switch platform for CTW3."""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.switch import (
    SwitchEntity,
    SwitchEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .client import CTW3State
from .const import DOMAIN
from .coordinator import CTW3Coordinator
from .entity import CTW3Entity


@dataclass(frozen=True, kw_only=True)
class CTW3SwitchEntityDescription(SwitchEntityDescription):
    is_on_fn: Callable[[CTW3State], bool | None]
    turn_on_fn: Callable[[CTW3Coordinator], Awaitable[None]]
    turn_off_fn: Callable[[CTW3Coordinator], Awaitable[None]]
    available_fn: Callable[[CTW3State], bool] = lambda s: True


def _power_on(c: CTW3Coordinator) -> Awaitable[None]:
    return c.async_set_power(True)


def _power_off(c: CTW3Coordinator) -> Awaitable[None]:
    return c.async_set_power(False)


def _suspend_on(c: CTW3Coordinator) -> Awaitable[None]:
    return c.async_set_suspend(True)


def _suspend_off(c: CTW3Coordinator) -> Awaitable[None]:
    return c.async_set_suspend(False)


def _lamp_on(c: CTW3Coordinator) -> Awaitable[None]:
    return c.async_set_lamp_ring(enabled=True)


def _lamp_off(c: CTW3Coordinator) -> Awaitable[None]:
    return c.async_set_lamp_ring(enabled=False)


def _dnd_on(c: CTW3Coordinator) -> Awaitable[None]:
    return c.async_set_dnd(True)


def _dnd_off(c: CTW3Coordinator) -> Awaitable[None]:
    return c.async_set_dnd(False)


def _lock_on(c: CTW3Coordinator) -> Awaitable[None]:
    return c.async_set_lock(True)


def _lock_off(c: CTW3Coordinator) -> Awaitable[None]:
    return c.async_set_lock(False)


def _smart_ind_on(c: CTW3Coordinator) -> Awaitable[None]:
    return c.async_set_smart_inductive(True)


def _smart_ind_off(c: CTW3Coordinator) -> Awaitable[None]:
    return c.async_set_smart_inductive(False)


def _batt_ind_on(c: CTW3Coordinator) -> Awaitable[None]:
    return c.async_set_battery_inductive(True)


def _batt_ind_off(c: CTW3Coordinator) -> Awaitable[None]:
    return c.async_set_battery_inductive(False)


SWITCHES: tuple[CTW3SwitchEntityDescription, ...] = (
    CTW3SwitchEntityDescription(
        key="power",
        translation_key="power",
        icon="mdi:power",
        is_on_fn=lambda s: bool(s.running.power_status) if s.running else None,
        turn_on_fn=_power_on,
        turn_off_fn=_power_off,
    ),
    CTW3SwitchEntityDescription(
        key="pause",
        translation_key="pause",
        icon="mdi:pause",
        is_on_fn=lambda s: bool(s.running.suspend_status) if s.running else None,
        turn_on_fn=_suspend_on,
        turn_off_fn=_suspend_off,
    ),
    CTW3SwitchEntityDescription(
        key="lamp_ring",
        translation_key="lamp_ring",
        icon="mdi:lightbulb-on",
        is_on_fn=lambda s: bool(s.settings.lamp_ring_switch) if s.settings else None,
        turn_on_fn=_lamp_on,
        turn_off_fn=_lamp_off,
    ),
    CTW3SwitchEntityDescription(
        key="dnd",
        translation_key="dnd",
        icon="mdi:sleep",
        is_on_fn=lambda s: bool(s.settings.no_disturbing_switch) if s.settings else None,
        turn_on_fn=_dnd_on,
        turn_off_fn=_dnd_off,
    ),
    CTW3SwitchEntityDescription(
        key="child_lock",
        translation_key="child_lock",
        icon="mdi:lock",
        entity_category=EntityCategory.CONFIG,
        is_on_fn=lambda s: bool(s.settings.is_lock)
        if s.settings and s.settings.is_lock is not None
        else None,
        available_fn=lambda s: s.supports_lock and s.settings is not None
        and s.settings.is_lock is not None,
        turn_on_fn=_lock_on,
        turn_off_fn=_lock_off,
    ),
    CTW3SwitchEntityDescription(
        key="smart_inductive",
        translation_key="smart_inductive",
        icon="mdi:motion-sensor",
        entity_category=EntityCategory.CONFIG,
        is_on_fn=lambda s: bool(s.settings.smart_inductive)
        if s.settings and s.settings.smart_inductive is not None
        else None,
        available_fn=lambda s: s.supports_inductive and s.settings is not None
        and s.settings.smart_inductive is not None,
        turn_on_fn=_smart_ind_on,
        turn_off_fn=_smart_ind_off,
    ),
    CTW3SwitchEntityDescription(
        key="battery_inductive",
        translation_key="battery_inductive",
        icon="mdi:motion-sensor",
        entity_category=EntityCategory.CONFIG,
        is_on_fn=lambda s: bool(s.settings.battery_inductive)
        if s.settings and s.settings.battery_inductive is not None
        else None,
        available_fn=lambda s: s.supports_inductive and s.settings is not None
        and s.settings.battery_inductive is not None,
        turn_on_fn=_batt_ind_on,
        turn_off_fn=_batt_ind_off,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: CTW3Coordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(CTW3Switch(coordinator, d) for d in SWITCHES)


class CTW3Switch(CTW3Entity, SwitchEntity):
    entity_description: CTW3SwitchEntityDescription

    def __init__(
        self,
        coordinator: CTW3Coordinator,
        description: CTW3SwitchEntityDescription,
    ) -> None:
        super().__init__(coordinator, key=description.key)
        self.entity_description = description

    @property
    def available(self) -> bool:
        if not super().available:
            return False
        state = self.coordinator.data
        return bool(state) and self.entity_description.available_fn(state)

    @property
    def is_on(self) -> bool | None:
        state = self.coordinator.data
        if state is None:
            return None
        return self.entity_description.is_on_fn(state)

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.entity_description.turn_on_fn(self.coordinator)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.entity_description.turn_off_fn(self.coordinator)
