"""DataUpdateCoordinator that owns the BLE session."""
from __future__ import annotations

import asyncio
import logging
from datetime import timedelta
from typing import Awaitable, Callable

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
                _LOGGER.debug("Reusing connected CTW3 BLE client for %s", self._address)
                return self._client
            ble_device = self._find_ble_device()
            if ble_device is None:
                _LOGGER.warning(
                    "CTW3 device %s was not found in Home Assistant Bluetooth cache",
                    self._address,
                )
                raise UpdateFailed(f"Device {self._address} not discovered by HA bluetooth")
            if self._client is None:
                _LOGGER.info(
                    "Creating CTW3 BLE client for %s (%s)",
                    self._device_name,
                    self._address,
                )
                self._client = CTW3BleClient(
                    ble_device,
                    self._secret,
                    name=self._device_name,
                    disconnect_callback=self._handle_disconnect,
                )
            else:
                # refresh BLEDevice reference (adv rotation)
                _LOGGER.debug("Refreshing CTW3 BLEDevice reference for %s", self._address)
                self._client._device = ble_device  # noqa: SLF001
            try:
                await self._client.handshake()
            except CTW3Error as err:
                await self._safe_disconnect()
                _LOGGER.warning(
                    "CTW3 handshake failed for %s (%s): %s",
                    self._device_name,
                    self._address,
                    err,
                )
                raise UpdateFailed(f"Handshake failed: {err}") from err
            return self._client

    def _handle_disconnect(self) -> None:
        _LOGGER.warning(
            "BLE disconnect for %s; coordinator will reconnect on next poll",
            self._address,
        )

    async def _async_update_data(self) -> CTW3State:
        last_err: Exception | None = None
        for attempt in range(2):
            try:
                client = await self._ensure_client()
                return await client.refresh_all()
            except (CTW3Error, UpdateFailed) as err:
                last_err = err
                await self._safe_disconnect()
                if attempt == 0:
                    _LOGGER.info(
                        "CTW3 refresh failed for %s (%s); reconnecting and retrying once: %s",
                        self._device_name,
                        self._address,
                        err,
                    )
                    await asyncio.sleep(0.5)
                    continue
                break
        if self.data is not None:
            _LOGGER.warning(
                "CTW3 update failed for %s (%s); keeping last known state: %s",
                self._device_name,
                self._address,
                last_err,
            )
            return self.data
        raise UpdateFailed(str(last_err))

    async def _safe_disconnect(self) -> None:
        if self._client is None:
            return
        client = self._client
        self._client = None
        try:
            await client.disconnect()
        except Exception:  # noqa: BLE001
            _LOGGER.debug("disconnect failed (ignored)", exc_info=True)

    async def _run_with_retry(
        self,
        label: str,
        action: Callable[[CTW3BleClient], Awaitable[None]],
    ) -> None:
        last_err: CTW3Error | None = None
        for attempt in range(2):
            client = await self._ensure_client()
            try:
                await action(client)
                self.async_set_updated_data(client.state)
                return
            except CTW3Error as err:
                last_err = err
                await self._safe_disconnect()
                if attempt == 0:
                    _LOGGER.info(
                        "CTW3 %s failed for %s (%s); reconnecting and retrying once: %s",
                        label,
                        self._device_name,
                        self._address,
                        err,
                    )
                    await asyncio.sleep(0.5)
                    continue
                raise
        if last_err is not None:
            raise last_err

    async def async_shutdown(self) -> None:  # type: ignore[override]
        await super().async_shutdown()
        await self._safe_disconnect()

    # ------------------------------------------------------------------
    # Convenience control wrappers used by entities
    # ------------------------------------------------------------------
    async def async_set_power(self, on: bool) -> None:
        await self._run_with_retry("set_power", lambda client: client.set_power(on))

    async def async_set_mode(self, mode: int) -> None:
        await self._run_with_retry("set_mode", lambda client: client.set_mode(mode))

    async def async_set_suspend(self, suspend: bool) -> None:
        await self._run_with_retry("set_suspend", lambda client: client.set_suspend(suspend))

    async def async_set_lamp_ring(self, enabled: bool | None = None, brightness: int | None = None) -> None:
        await self._run_with_retry(
            "set_lamp_ring",
            lambda client: client.set_lamp_ring(enabled=enabled, brightness=brightness),
        )

    async def async_set_dnd(self, enabled: bool) -> None:
        await self._run_with_retry("set_dnd", lambda client: client.set_dnd(enabled))

    async def async_set_lock(self, locked: bool) -> None:
        await self._run_with_retry("set_lock", lambda client: client.set_lock(locked))

    async def async_set_smart_inductive(self, enabled: bool) -> None:
        await self._run_with_retry(
            "set_smart_inductive",
            lambda client: client.set_smart_inductive(enabled),
        )

    async def async_set_battery_inductive(self, enabled: bool) -> None:
        await self._run_with_retry(
            "set_battery_inductive",
            lambda client: client.set_battery_inductive(enabled),
        )

    async def async_set_smart_times(
        self, working_minutes: int | None = None, sleep_minutes: int | None = None
    ) -> None:
        await self._run_with_retry(
            "set_smart_times",
            lambda client: client.set_smart_times(working_minutes, sleep_minutes),
        )

    async def async_set_battery_times(
        self, working_seconds: int | None = None, sleep_seconds: int | None = None
    ) -> None:
        await self._run_with_retry(
            "set_battery_times",
            lambda client: client.set_battery_times(working_seconds, sleep_seconds),
        )

    async def async_reset_filter(self) -> None:
        await self._run_with_retry("reset_filter", lambda client: client.reset_filter())

    async def async_write_light_schedule(
        self,
        enabled: bool,
        entries: list[tuple[int, int, int]] | None = None,
    ) -> None:
        await self._run_with_retry(
            "write_light_schedule",
            lambda client: client.write_light_schedule(enabled=enabled, entries=entries),
        )

    async def async_write_dnd_schedule(
        self,
        enabled: bool,
        entries: list[tuple[int, int, int]] | None = None,
    ) -> None:
        await self._run_with_retry(
            "write_dnd_schedule",
            lambda client: client.write_dnd_schedule(enabled=enabled, entries=entries),
        )

    async def async_sync_history(self) -> None:
        await self._run_with_retry("sync_history", lambda client: client.sync_history())
