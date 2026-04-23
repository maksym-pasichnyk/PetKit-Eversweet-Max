"""Extra services for CTW3 (schedule writes, sync history)."""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant.const import ATTR_DEVICE_ID
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import device_registry as dr

from .const import DOMAIN
from .coordinator import CTW3Coordinator

_LOGGER = logging.getLogger(__name__)

SERVICE_WRITE_LIGHT_SCHEDULE = "write_light_schedule"
SERVICE_WRITE_DND_SCHEDULE = "write_dnd_schedule"
SERVICE_SYNC_HISTORY = "sync_history"

SCHEDULE_ENTRY_SCHEMA = vol.Schema(
    {
        vol.Required("start"): vol.All(int, vol.Range(min=0, max=24 * 60 - 1)),
        vol.Required("end"): vol.All(int, vol.Range(min=0, max=24 * 60)),
        vol.Optional("weekday_mask", default=0x7F): vol.All(int, vol.Range(min=0, max=0xFF)),
    }
)

WRITE_SCHEDULE_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_DEVICE_ID): cv.string,
        vol.Required("enabled"): cv.boolean,
        vol.Optional("entries", default=list): [SCHEDULE_ENTRY_SCHEMA],
    }
)

SYNC_HISTORY_SCHEMA = vol.Schema({vol.Required(ATTR_DEVICE_ID): cv.string})


def _coordinator_for_device(hass: HomeAssistant, device_id: str) -> CTW3Coordinator:
    dev_reg = dr.async_get(hass)
    device = dev_reg.async_get(device_id)
    if device is None:
        raise HomeAssistantError(f"Device {device_id} not found")
    for entry_id in device.config_entries:
        coordinator = hass.data.get(DOMAIN, {}).get(entry_id)
        if isinstance(coordinator, CTW3Coordinator):
            return coordinator
    raise HomeAssistantError(f"No CTW3 coordinator for device {device_id}")


def _entries_from_call(call: ServiceCall) -> list[tuple[int, int, int]]:
    entries_raw: list[dict[str, Any]] = call.data.get("entries", [])
    return [
        (int(e["start"]), int(e["end"]), int(e.get("weekday_mask", 0x7F)))
        for e in entries_raw
    ]


@callback
def async_register_services(hass: HomeAssistant) -> None:
    if hass.services.has_service(DOMAIN, SERVICE_WRITE_LIGHT_SCHEDULE):
        return

    async def _handle_light(call: ServiceCall) -> None:
        coordinator = _coordinator_for_device(hass, call.data[ATTR_DEVICE_ID])
        await coordinator.async_write_light_schedule(
            enabled=call.data["enabled"], entries=_entries_from_call(call)
        )

    async def _handle_dnd(call: ServiceCall) -> None:
        coordinator = _coordinator_for_device(hass, call.data[ATTR_DEVICE_ID])
        await coordinator.async_write_dnd_schedule(
            enabled=call.data["enabled"], entries=_entries_from_call(call)
        )

    async def _handle_sync(call: ServiceCall) -> None:
        coordinator = _coordinator_for_device(hass, call.data[ATTR_DEVICE_ID])
        await coordinator.async_sync_history()

    hass.services.async_register(
        DOMAIN, SERVICE_WRITE_LIGHT_SCHEDULE, _handle_light, schema=WRITE_SCHEDULE_SCHEMA
    )
    hass.services.async_register(
        DOMAIN, SERVICE_WRITE_DND_SCHEDULE, _handle_dnd, schema=WRITE_SCHEDULE_SCHEMA
    )
    hass.services.async_register(
        DOMAIN, SERVICE_SYNC_HISTORY, _handle_sync, schema=SYNC_HISTORY_SCHEMA
    )
