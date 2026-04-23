"""Number platform for CTW3 (Smart/Battery work+sleep durations, lamp brightness)."""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from homeassistant.components.number import (
    NumberEntity,
    NumberEntityDescription,
    NumberMode,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE, EntityCategory, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .client import CTW3State
from .const import DOMAIN
from .coordinator import CTW3Coordinator
from .entity import CTW3Entity


@dataclass(frozen=True, kw_only=True)
class CTW3NumberEntityDescription(NumberEntityDescription):
    value_fn: Callable[[CTW3State], float | None]
    set_fn: Callable[[CTW3Coordinator, int], Awaitable[None]]


async def _set_smart_work(c: CTW3Coordinator, v: int) -> None:
    await c.async_set_smart_times(working_minutes=v)


async def _set_smart_sleep(c: CTW3Coordinator, v: int) -> None:
    await c.async_set_smart_times(sleep_minutes=v)


async def _set_batt_work(c: CTW3Coordinator, v: int) -> None:
    await c.async_set_battery_times(working_seconds=v)


async def _set_batt_sleep(c: CTW3Coordinator, v: int) -> None:
    await c.async_set_battery_times(sleep_seconds=v)


async def _set_brightness(c: CTW3Coordinator, v: int) -> None:
    await c.async_set_lamp_ring(brightness=v)


NUMBERS: tuple[CTW3NumberEntityDescription, ...] = (
    CTW3NumberEntityDescription(
        key="smart_work_minutes",
        translation_key="smart_work_minutes",
        native_unit_of_measurement=UnitOfTime.MINUTES,
        native_min_value=1,
        native_max_value=120,
        native_step=1,
        mode=NumberMode.BOX,
        entity_category=EntityCategory.CONFIG,
        icon="mdi:timer-play",
        value_fn=lambda s: s.settings.smart_working_min if s.settings else None,
        set_fn=_set_smart_work,
    ),
    CTW3NumberEntityDescription(
        key="smart_sleep_minutes",
        translation_key="smart_sleep_minutes",
        native_unit_of_measurement=UnitOfTime.MINUTES,
        native_min_value=1,
        native_max_value=240,
        native_step=1,
        mode=NumberMode.BOX,
        entity_category=EntityCategory.CONFIG,
        icon="mdi:timer-sand",
        value_fn=lambda s: s.settings.smart_sleep_min if s.settings else None,
        set_fn=_set_smart_sleep,
    ),
    CTW3NumberEntityDescription(
        key="battery_work_seconds",
        translation_key="battery_work_seconds",
        native_unit_of_measurement=UnitOfTime.SECONDS,
        native_min_value=30,
        native_max_value=600,
        native_step=5,
        mode=NumberMode.BOX,
        entity_category=EntityCategory.CONFIG,
        icon="mdi:timer-play",
        value_fn=lambda s: s.settings.battery_working_s if s.settings else None,
        set_fn=_set_batt_work,
    ),
    CTW3NumberEntityDescription(
        key="battery_sleep_seconds",
        translation_key="battery_sleep_seconds",
        native_unit_of_measurement=UnitOfTime.SECONDS,
        native_min_value=60,
        native_max_value=3600,
        native_step=10,
        mode=NumberMode.BOX,
        entity_category=EntityCategory.CONFIG,
        icon="mdi:timer-sand",
        value_fn=lambda s: s.settings.battery_sleep_s if s.settings else None,
        set_fn=_set_batt_sleep,
    ),
    CTW3NumberEntityDescription(
        key="lamp_brightness",
        translation_key="lamp_brightness",
        native_unit_of_measurement=PERCENTAGE,
        native_min_value=0,
        native_max_value=100,
        native_step=1,
        mode=NumberMode.SLIDER,
        entity_category=EntityCategory.CONFIG,
        icon="mdi:brightness-6",
        value_fn=lambda s: s.settings.lamp_ring_brightness if s.settings else None,
        set_fn=_set_brightness,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: CTW3Coordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(CTW3Number(coordinator, d) for d in NUMBERS)


class CTW3Number(CTW3Entity, NumberEntity):
    entity_description: CTW3NumberEntityDescription

    def __init__(
        self,
        coordinator: CTW3Coordinator,
        description: CTW3NumberEntityDescription,
    ) -> None:
        super().__init__(coordinator, key=description.key)
        self.entity_description = description

    @property
    def native_value(self) -> float | None:
        state = self.coordinator.data
        if state is None:
            return None
        return self.entity_description.value_fn(state)

    async def async_set_native_value(self, value: float) -> None:
        await self.entity_description.set_fn(self.coordinator, int(value))
