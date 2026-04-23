"""DataUpdateCoordinator that owns the BLE session."""
from __future__ import annotations

import asyncio
import logging
from datetime import timedelta

from bleak.backends.device import BLEDevice
from homeassistant.components import bluetooth
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .client import CTW3BleClient, CTW3Error, CTW3State
from .const import DEFAULT_SCAN_INTERVAL, DOMAIN

_LOGGER = logging.getLogger(__name__)


class CTW3Coordinator(DataUpdateCoordinator[CTW3State]):
    """Polls the CTW3 device via BLE and exposes the current CTW3State."""

    def __init__(
        self,
        hass: HomeAssistant,
        *,
        address: str,
        secret: bytes,
        name: str,
        scan_interval: int = DEFAULT_SCAN_INTERVAL,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}:{address}",
            update_interval=timedelta(seconds=scan_interval),
        )
        self._address = address
        self._secret = secret
        self._device_name = name
        self._client: CTW3BleClient | None = None
        self._client_lock = asyncio.Lock()

    @property
    def address(self) -> str:
        return self._address

    @property
    def device_name(self) -> str:
        return self._device_name

    @property
    def client(self) -> CTW3BleClient | None:
        return self._client

    def _find_ble_device(self) -> BLEDevice | None:
        return bluetooth.async_ble_device_from_address(
            self.hass, self._address, connectable=True
        )

    async def _ensure_client(self) -> CTW3BleClient:
        async with self._client_lock:
            if self._client is not None and self._client.state.connected:
                return self._client
            ble_device = self._find_ble_device()
            if ble_device is None:
                raise UpdateFailed(f"Device {self._address} not discovered by HA bluetooth")
            if self._client is None:
                self._client = CTW3BleClient(
                    ble_device,
                    self._secret,
                    name=self._device_name,
                    disconnect_callback=self._handle_disconnect,
                )
            else:
                # refresh BLEDevice reference (adv rotation)
                self._client._device = ble_device  # noqa: SLF001
            try:
                await self._client.handshake()
            except CTW3Error as err:
                raise UpdateFailed(f"Handshake failed: {err}") from err
            return self._client

    def _handle_disconnect(self) -> None:
        _LOGGER.debug("BLE disconnect for %s — coordinator will reconnect on next poll", self._address)

    async def _async_update_data(self) -> CTW3State:
        client = await self._ensure_client()
        try:
            state = await client.refresh_all()
        except CTW3Error as err:
            # drop client so next poll re-handshakes
            await self._safe_disconnect()
            raise UpdateFailed(str(err)) from err
        return state

    async def _safe_disconnect(self) -> None:
        if self._client is None:
            return
        try:
            await self._client.disconnect()
        except Exception:  # noqa: BLE001
            _LOGGER.debug("disconnect failed (ignored)", exc_info=True)

    async def async_shutdown(self) -> None:  # type: ignore[override]
        await super().async_shutdown()
        await self._safe_disconnect()

    # ------------------------------------------------------------------
    # Convenience control wrappers used by entities
    # ------------------------------------------------------------------
    async def async_set_power(self, on: bool) -> None:
        client = await self._ensure_client()
        await client.set_power(on)
        self.async_set_updated_data(client.state)

    async def async_set_mode(self, mode: int) -> None:
        client = await self._ensure_client()
        await client.set_mode(mode)
        self.async_set_updated_data(client.state)

    async def async_set_suspend(self, suspend: bool) -> None:
        client = await self._ensure_client()
        await client.set_suspend(suspend)
        self.async_set_updated_data(client.state)

    async def async_set_lamp_ring(self, enabled: bool | None = None, brightness: int | None = None) -> None:
        client = await self._ensure_client()
        await client.set_lamp_ring(enabled=enabled, brightness=brightness)
        self.async_set_updated_data(client.state)

    async def async_set_dnd(self, enabled: bool) -> None:
        client = await self._ensure_client()
        await client.set_dnd(enabled)
        self.async_set_updated_data(client.state)

    async def async_set_lock(self, locked: bool) -> None:
        client = await self._ensure_client()
        await client.set_lock(locked)
        self.async_set_updated_data(client.state)

    async def async_set_smart_inductive(self, enabled: bool) -> None:
        client = await self._ensure_client()
        await client.set_smart_inductive(enabled)
        self.async_set_updated_data(client.state)

    async def async_set_battery_inductive(self, enabled: bool) -> None:
        client = await self._ensure_client()
        await client.set_battery_inductive(enabled)
        self.async_set_updated_data(client.state)

    async def async_set_smart_times(
        self, working_minutes: int | None = None, sleep_minutes: int | None = None
    ) -> None:
        client = await self._ensure_client()
        await client.set_smart_times(working_minutes, sleep_minutes)
        self.async_set_updated_data(client.state)

    async def async_set_battery_times(
        self, working_seconds: int | None = None, sleep_seconds: int | None = None
    ) -> None:
        client = await self._ensure_client()
        await client.set_battery_times(working_seconds, sleep_seconds)
        self.async_set_updated_data(client.state)

    async def async_reset_filter(self) -> None:
        client = await self._ensure_client()
        await client.reset_filter()
        self.async_set_updated_data(client.state)

    async def async_write_light_schedule(
        self,
        enabled: bool,
        entries: list[tuple[int, int, int]] | None = None,
    ) -> None:
        client = await self._ensure_client()
        await client.write_light_schedule(enabled=enabled, entries=entries)
        self.async_set_updated_data(client.state)

    async def async_write_dnd_schedule(
        self,
        enabled: bool,
        entries: list[tuple[int, int, int]] | None = None,
    ) -> None:
        client = await self._ensure_client()
        await client.write_dnd_schedule(enabled=enabled, entries=entries)
        self.async_set_updated_data(client.state)

    async def async_sync_history(self) -> None:
        client = await self._ensure_client()
        await client.sync_history()
        self.async_set_updated_data(client.state)
