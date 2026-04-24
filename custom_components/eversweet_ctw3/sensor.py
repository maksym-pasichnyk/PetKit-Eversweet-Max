"""Sensor platform for CTW3."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    PERCENTAGE,
    EntityCategory,
    UnitOfElectricPotential,
    UnitOfTime,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .client import CTW3State
from .const import DOMAIN
from .coordinator import CTW3Coordinator
from .entity import CTW3Entity


@dataclass(frozen=True, kw_only=True)
class CTW3SensorEntityDescription(SensorEntityDescription):
    value_fn: Callable[[CTW3State], Any]


def _battery_pct(state: CTW3State) -> int | None:
    if state.battery is not None and state.battery.percent is not None:
        return state.battery.percent
    if state.running is not None and state.running.battery_percent is not None:
        return state.running.battery_percent
    return None


def _battery_v(state: CTW3State) -> float | None:
    mv = None
    if state.battery is not None:
        mv = state.battery.voltage_mv
    elif state.running is not None:
        mv = state.running.battery_voltage_mv
    return round(mv / 1000.0, 3) if mv is not None else None


def _supply_v(state: CTW3State) -> float | None:
    if state.running is None:
        return None
    mv = state.running.supply_voltage_mv
    return round(mv / 1000.0, 3) if mv is not None else None


def _filter_pct(state: CTW3State) -> int | None:
    return state.running.filter_percent if state.running else None


def _today_pump_time(state: CTW3State) -> int | None:
    return state.running.today_pump_run_time if state.running else None


def _total_pump_time(state: CTW3State) -> int | None:
    return state.running.water_pump_run_time if state.running else None


def _run_status(state: CTW3State) -> int | None:
    return state.running.run_status if state.running else None


def _module_status(state: CTW3State) -> int | None:
    return state.running.module_status if state.running else None


def _firmware(state: CTW3State) -> str | None:
    if state.firmware is None:
        return None
    return f"{state.hardware or 0}.{state.firmware}"


def _last_drink(state: CTW3State) -> datetime | None:
    if not state.work_history:
        return None
    ts = max(entry.work_time_posix for entry in state.work_history)
    return datetime.fromtimestamp(ts, tz=timezone.utc)


def _restart_times(state: CTW3State) -> int | None:
    return state.device_log.restart_times if state.device_log else None


def _run_time(state: CTW3State) -> int | None:
    return state.device_log.run_time if state.device_log else None


def _pump_times(state: CTW3State) -> int | None:
    return state.device_log.pump_times if state.device_log else None


SENSORS: tuple[CTW3SensorEntityDescription, ...] = (
    # ── Sensors (visible at a glance, no category) ──────────────────────
    CTW3SensorEntityDescription(
        key="battery",
        translation_key="battery",
        device_class=SensorDeviceClass.BATTERY,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=PERCENTAGE,
        # Not DIAGNOSTIC — users check battery daily
        value_fn=_battery_pct,
    ),
    CTW3SensorEntityDescription(
        key="filter_percent",
        translation_key="filter_percent",
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=PERCENTAGE,
        icon="mdi:air-filter",
        value_fn=_filter_pct,
    ),
    CTW3SensorEntityDescription(
        key="pump_time_today",
        translation_key="pump_time_today",
        device_class=SensorDeviceClass.DURATION,
        state_class=SensorStateClass.TOTAL_INCREASING,
        native_unit_of_measurement=UnitOfTime.SECONDS,
        icon="mdi:water-pump",
        value_fn=_today_pump_time,
    ),
    CTW3SensorEntityDescription(
        key="last_drink",
        translation_key="last_drink",
        device_class=SensorDeviceClass.TIMESTAMP,
        icon="mdi:clock-outline",
        value_fn=_last_drink,
    ),
    # ── Diagnostic ───────────────────────────────────────────────────────
    CTW3SensorEntityDescription(
        key="battery_voltage",
        translation_key="battery_voltage",
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_battery_v,
    ),
    CTW3SensorEntityDescription(
        key="supply_voltage",
        translation_key="supply_voltage",
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_supply_v,
    ),
    CTW3SensorEntityDescription(
        key="pump_time_total",
        translation_key="pump_time_total",
        device_class=SensorDeviceClass.DURATION,
        state_class=SensorStateClass.TOTAL_INCREASING,
        native_unit_of_measurement=UnitOfTime.SECONDS,
        icon="mdi:water-pump",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_total_pump_time,
    ),
    CTW3SensorEntityDescription(
        key="firmware",
        translation_key="firmware",
        entity_category=EntityCategory.DIAGNOSTIC,
        icon="mdi:chip",
        value_fn=_firmware,
    ),
    CTW3SensorEntityDescription(
        key="restart_times",
        translation_key="restart_times",
        entity_category=EntityCategory.DIAGNOSTIC,
        state_class=SensorStateClass.TOTAL_INCREASING,
        icon="mdi:restart",
        value_fn=_restart_times,
    ),
    CTW3SensorEntityDescription(
        key="run_time_seconds",
        translation_key="run_time_seconds",
        entity_category=EntityCategory.DIAGNOSTIC,
        device_class=SensorDeviceClass.DURATION,
        state_class=SensorStateClass.TOTAL_INCREASING,
        native_unit_of_measurement=UnitOfTime.SECONDS,
        value_fn=_run_time,
    ),
    CTW3SensorEntityDescription(
        key="pump_times_total",
        translation_key="pump_times_total",
        entity_category=EntityCategory.DIAGNOSTIC,
        state_class=SensorStateClass.TOTAL_INCREASING,
        icon="mdi:counter",
        value_fn=_pump_times,
    ),
    CTW3SensorEntityDescription(
        key="run_status",
        translation_key="run_status",
        entity_category=EntityCategory.DIAGNOSTIC,
        icon="mdi:information-outline",
        value_fn=_run_status,
    ),
    CTW3SensorEntityDescription(
        key="module_status",
        translation_key="module_status",
        entity_category=EntityCategory.DIAGNOSTIC,
        icon="mdi:information-outline",
        value_fn=_module_status,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: CTW3Coordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(CTW3Sensor(coordinator, d) for d in SENSORS)


class CTW3Sensor(CTW3Entity, SensorEntity):
    entity_description: CTW3SensorEntityDescription

    def __init__(
        self, coordinator: CTW3Coordinator, description: CTW3SensorEntityDescription
    ) -> None:
        super().__init__(coordinator, key=description.key)
        self.entity_description = description

    @property
    def native_value(self) -> Any:
        state = self.coordinator.data
        if state is None:
            return None
        return self.entity_description.value_fn(state)
