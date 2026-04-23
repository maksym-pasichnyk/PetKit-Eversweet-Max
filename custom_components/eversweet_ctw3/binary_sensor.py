"""Binary sensor platform for CTW3."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
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
class CTW3BinarySensorEntityDescription(BinarySensorEntityDescription):
    value_fn: Callable[[CTW3State], bool | None]


def _lack_water(s: CTW3State) -> bool | None:
    return bool(s.running.lack_warning) if s.running else None


def _low_battery(s: CTW3State) -> bool | None:
    return bool(s.running.low_battery) if s.running else None


def _filter(s: CTW3State) -> bool | None:
    return bool(s.running.filter_warning) if s.running else None


def _breakdown(s: CTW3State) -> bool | None:
    return bool(s.running.breakdown_warning) if s.running else None


def _night_dnd(s: CTW3State) -> bool | None:
    return bool(s.running.is_night_no_disturbing) if s.running else None


def _dc_connected(s: CTW3State) -> bool | None:
    return bool(s.running.electric_status) if s.running else None


def _running(s: CTW3State) -> bool | None:
    if s.running is None:
        return None
    return bool(s.running.power_status and not s.running.suspend_status)


def _pet_detected(s: CTW3State) -> bool | None:
    return bool(s.running.detect_status) if s.running else None


SENSORS: tuple[CTW3BinarySensorEntityDescription, ...] = (
    CTW3BinarySensorEntityDescription(
        key="lack_water",
        translation_key="lack_water",
        device_class=BinarySensorDeviceClass.PROBLEM,
        icon="mdi:water-off",
        value_fn=_lack_water,
    ),
    CTW3BinarySensorEntityDescription(
        key="low_battery",
        translation_key="low_battery",
        device_class=BinarySensorDeviceClass.BATTERY,
        value_fn=_low_battery,
    ),
    CTW3BinarySensorEntityDescription(
        key="filter_warning",
        translation_key="filter_warning",
        device_class=BinarySensorDeviceClass.PROBLEM,
        icon="mdi:air-filter",
        value_fn=_filter,
    ),
    CTW3BinarySensorEntityDescription(
        key="breakdown",
        translation_key="breakdown",
        device_class=BinarySensorDeviceClass.PROBLEM,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_breakdown,
    ),
    CTW3BinarySensorEntityDescription(
        key="night_dnd",
        translation_key="night_dnd",
        icon="mdi:sleep",
        value_fn=_night_dnd,
    ),
    CTW3BinarySensorEntityDescription(
        key="dc_connected",
        translation_key="dc_connected",
        device_class=BinarySensorDeviceClass.POWER,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_dc_connected,
    ),
    CTW3BinarySensorEntityDescription(
        key="running",
        translation_key="running",
        device_class=BinarySensorDeviceClass.RUNNING,
        value_fn=_running,
    ),
    CTW3BinarySensorEntityDescription(
        key="pet_detected",
        translation_key="pet_detected",
        device_class=BinarySensorDeviceClass.MOTION,
        value_fn=_pet_detected,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: CTW3Coordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(CTW3BinarySensor(coordinator, d) for d in SENSORS)


class CTW3BinarySensor(CTW3Entity, BinarySensorEntity):
    entity_description: CTW3BinarySensorEntityDescription

    def __init__(
        self,
        coordinator: CTW3Coordinator,
        description: CTW3BinarySensorEntityDescription,
    ) -> None:
        super().__init__(coordinator, key=description.key)
        self.entity_description = description

    @property
    def is_on(self) -> bool | None:
        state = self.coordinator.data
        if state is None:
            return None
        return self.entity_description.value_fn(state)
