"""Base entity for CTW3 integration."""
from __future__ import annotations

from homeassistant.helpers.device_registry import CONNECTION_BLUETOOTH, DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import CTW3Coordinator


class CTW3Entity(CoordinatorEntity[CTW3Coordinator]):
    """Base entity binding entities to the coordinator + device registry."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: CTW3Coordinator, *, key: str) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.address}-{key}"
        state = coordinator.data
        sn = state.sn if state else None
        firmware = state.firmware if state else None
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.address)},
            connections={(CONNECTION_BLUETOOTH, coordinator.address)},
            manufacturer="PetKit",
            model="Eversweet Max Smart (CTW3)",
            name=coordinator.device_name,
            serial_number=sn,
            sw_version=str(firmware) if firmware is not None else None,
        )

    @property
    def available(self) -> bool:
        return super().available and self.coordinator.data is not None
