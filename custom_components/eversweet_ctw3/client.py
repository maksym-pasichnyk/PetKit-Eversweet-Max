"""BLE client for the PetKit CTW3 (Eversweet Max Smart) water fountain.

Implements the full handshake + command/response flow reverse-engineered
from the decompiled APK (CTW3BleClient / PetkitBleClient / *DataConvertor).
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Awaitable, Callable

from bleak import BleakClient
from bleak.backends.device import BLEDevice
from bleak.exc import BleakError
from bleak_retry_connector import (
    BleakClientWithServiceCache,
    establish_connection,
)

from .const import (
    CMD_CHECK_STREAM_DATA,
    CMD_CONTROL,
    CMD_DEVICE_UPDATE_PUSH,
    CMD_DND_SCHEDULE,
    CMD_FULL_SETTINGS,
    CMD_GET_DEVICE_ID,
    CMD_GET_DEVICE_LOG,
    CMD_GET_FIRMWARE,
    CMD_LIGHT_SCHEDULE,
    CMD_RESET_FILTER,
    CMD_RUNNING_INFO,
    CMD_SECURITY_CHECK,
    CMD_SET_STREAM_SETTING,
    CMD_SETTINGS,
    CMD_START_SYNC_HISTORY,
    CMD_STREAM_END,
    CMD_STREAM_PUSH_68,
    CMD_STREAM_PUSH_82,
    CMD_SYNC_BATTERY,
    CMD_SYNC_TIME,
    CMD_WRITE_DND_SCHEDULE,
    CMD_WRITE_LIGHT_SCHEDULE,
    CONNECT_TIMEOUT,
    CONTROL_CHAR_UUID,
    DATA_CHAR_UUID,
    DEFAULT_MTU,
    MODE_BATTERY,
    MODE_INTERMITTENT,
    MODE_STANDARD,
    NOTIFICATION_TIMEOUT,
    TYPE_REQUEST,
    TYPE_RESPONSE,
)
from .protocol import (
    BatteryInfo,
    DeviceIdInfo,
    DeviceLog,
    FirmwareInfo,
    Frame,
    FrameDecoder,
    RunningInfo,
    ScheduleInfo,
    SettingsInfo,
    WorkDataEntry,
    build_control,
    build_full_settings,
    build_schedule,
    build_security_check,
    build_stream_ack_bitmask,
    build_stream_setting,
    build_sync_time_payload,
    encode_command,
    parse_battery,
    parse_device_id,
    parse_device_log,
    parse_firmware,
    parse_running_info,
    parse_schedule,
    parse_settings,
    parse_work_data_stream,
)

_LOGGER = logging.getLogger(__name__)


class CTW3Error(Exception):
    """Base error for CTW3 client."""


class CTW3AuthError(CTW3Error):
    """Security check (cmd 86) did not succeed — wrong secret."""


class CTW3Timeout(CTW3Error):
    """Timed out waiting for a frame."""


@dataclass
class CTW3State:
    """Snapshot of device data exposed to the HA layer."""

    connected: bool = False
    device_id: int | None = None
    sn: str | None = None
    hardware: int | None = None
    firmware: int | None = None

    battery: BatteryInfo | None = None
    running: RunningInfo | None = None
    settings: SettingsInfo | None = None
    light_schedule: ScheduleInfo | None = None
    dnd_schedule: ScheduleInfo | None = None
    device_log: DeviceLog | None = None

    work_history: list[WorkDataEntry] = field(default_factory=list)

    @property
    def supports_lock(self) -> bool:
        if self.hardware is None or self.firmware is None:
            return False
        # isSupportLockVersion: hardware + firmware/100 >= 1.35
        return (self.hardware + self.firmware / 100.0) >= 1.35

    @property
    def supports_inductive(self) -> bool:
        return self.firmware is not None and self.firmware >= 89


class CTW3BleClient:
    """Async BLE client that manages a single CTW3 device session."""

    def __init__(
        self,
        device: BLEDevice,
        secret: bytes,
        *,
        name: str | None = None,
        disconnect_callback: Callable[[], None] | None = None,
    ) -> None:
        self._device = device
        self._secret = secret
        self._name = name or device.name or "CTW3"
        self._disconnect_cb = disconnect_callback

        self._client: BleakClient | None = None
        self._decoder = FrameDecoder()
        self._seq = -1
        self._lock = asyncio.Lock()
        self._operation_lock = asyncio.Lock()
        self._write_lock = asyncio.Lock()

        # response plumbing
        self._pending: dict[tuple[int, int], asyncio.Future[Frame]] = {}
        self._stream_buffers: dict[int, bytearray] = {}
        self._stream_received: set[int] = set()
        self._stream_total = 0
        self._stream_check_queue: asyncio.Queue[Frame] = asyncio.Queue()
        self._stream_end_event = asyncio.Event()

        self.state = CTW3State()

        # optional callback when state changes
        self.on_state_update: Callable[[CTW3State], None] | None = None
        self.on_work_history: Callable[[list[WorkDataEntry]], Awaitable[None] | None] | None = None

    # ------------------------------------------------------------------
    # Connection lifecycle
    # ------------------------------------------------------------------
    async def connect(self) -> None:
        async with self._lock:
            if self._client is not None and self._client.is_connected:
                return
            _LOGGER.debug("Connecting to %s (%s)", self._name, self._device.address)
            self._client = await establish_connection(
                BleakClientWithServiceCache,
                self._device,
                self._name,
                disconnected_callback=self._handle_disconnect,
                max_attempts=3,
                timeout=CONNECT_TIMEOUT,
            )
            # MTU on Android/Linux is negotiated automatically; bleak exposes it as a property
            try:
                # Some backends allow explicit negotiation
                await self._client._backend._acquire_mtu()  # type: ignore[attr-defined]
            except Exception:  # pragma: no cover - backend-specific
                pass
            await self._client.start_notify(DATA_CHAR_UUID, self._on_notify)
            self.state.connected = True
            _LOGGER.debug("Connected to %s", self._name)

    async def disconnect(self) -> None:
        async with self._lock:
            if self._client is None:
                return
            try:
                if self._client.is_connected:
                    try:
                        await self._client.stop_notify(DATA_CHAR_UUID)
                    except Exception:  # noqa: BLE001
                        pass
                    await self._client.disconnect()
            finally:
                self._client = None
                self.state.connected = False

    def _handle_disconnect(self, _client: BleakClient) -> None:
        _LOGGER.debug("Device %s disconnected", self._name)
        self.state.connected = False
        # fail any pending futures
        for fut in list(self._pending.values()):
            if not fut.done():
                fut.set_exception(CTW3Error("disconnected"))
        self._pending.clear()
        if self._disconnect_cb:
            try:
                self._disconnect_cb()
            except Exception:  # noqa: BLE001
                _LOGGER.exception("disconnect callback failed")

    # ------------------------------------------------------------------
    # Low-level notify / send
    # ------------------------------------------------------------------
    def _on_notify(self, _sender, data: bytearray) -> None:
        frames = self._decoder.feed(bytes(data))
        for frame in frames:
            _LOGGER.debug("<- %s", frame)
            try:
                self._dispatch_frame(frame)
            except Exception:  # noqa: BLE001
                _LOGGER.exception("Error dispatching frame")

    def _dispatch_frame(self, frame: Frame) -> None:
        if frame.is_stream:
            self._handle_stream_frame(frame)
            return
        # Async device-initiated push (cmd 230 FW/param update) — ack it
        if frame.cmd == CMD_DEVICE_UPDATE_PUSH and frame.type == TYPE_REQUEST:
            asyncio.create_task(
                self._send_frame(
                    CMD_DEVICE_UPDATE_PUSH,
                    TYPE_RESPONSE,
                    bytes([0x01]),
                    sequence=frame.sequence,
                )
            )
            return
        if frame.cmd == CMD_CHECK_STREAM_DATA and frame.type == TYPE_REQUEST:
            self._stream_check_queue.put_nowait(frame)
            return
        # Device-initiated stream close from device: cmd 69 type=1 — ack with type=2
        if frame.cmd == CMD_STREAM_END and frame.type == TYPE_REQUEST:
            self._stream_end_event.set()
            asyncio.create_task(
                self._send_frame(
                    CMD_STREAM_END,
                    TYPE_RESPONSE,
                    b"",
                    sequence=frame.sequence,
                )
            )
            return
        if frame.type != TYPE_RESPONSE:
            return
        # complete pending request
        fut = self._pending.pop((frame.cmd, frame.sequence), None)
        if fut is not None and not fut.done():
            fut.set_result(frame)

    def _handle_stream_frame(self, frame: Frame) -> None:
        if frame.cmd in (CMD_STREAM_PUSH_68, CMD_STREAM_PUSH_82):
            self._stream_buffers[frame.index] = bytearray(frame.data)
            self._stream_received.add(frame.index)
            self._stream_total = frame.total

    async def _send_frame(
        self,
        cmd: int,
        frame_type: int,
        data: bytes,
        *,
        sequence: int | None = None,
    ) -> int:
        if self._client is None or not self._client.is_connected:
            raise CTW3Error("not connected")
        seq = self._next_seq() if sequence is None else sequence
        raw = encode_command(cmd, frame_type, seq, data)
        _LOGGER.debug("-> cmd=%d type=%d seq=%d data=%s", cmd, frame_type, seq, data.hex())
        async with self._write_lock:
            await self._client.write_gatt_char(CONTROL_CHAR_UUID, raw, response=True)
        return seq

    def _next_seq(self) -> int:
        self._seq = (self._seq + 1) & 0xFF
        return self._seq

    async def _request(
        self,
        cmd: int,
        data: bytes = b"",
        *,
        response_cmd: int | None = None,
        timeout: float = NOTIFICATION_TIMEOUT,
    ) -> Frame:
        """Send a REQUEST frame and wait for the device's RESPONSE for the same cmd."""
        target_cmd = response_cmd if response_cmd is not None else cmd
        loop = asyncio.get_running_loop()
        future: asyncio.Future[Frame] = loop.create_future()
        seq = self._next_seq()
        pending_key = (target_cmd, seq)
        old = self._pending.pop(pending_key, None)
        if old and not old.done():
            old.cancel()
        self._pending[pending_key] = future
        try:
            await self._send_frame(cmd, TYPE_REQUEST, data, sequence=seq)
            return await asyncio.wait_for(future, timeout=timeout)
        except asyncio.TimeoutError as err:
            raise CTW3Timeout(
                f"timeout waiting for cmd {target_cmd} seq {seq}"
            ) from err
        finally:
            self._pending.pop(pending_key, None)

    # ------------------------------------------------------------------
    # Handshake
    # ------------------------------------------------------------------
    async def handshake(self) -> None:
        """Run the full handshake sequence."""
        async with self._operation_lock:
            await self.connect()

            # 1. Identify
            frame = await self._request(CMD_GET_DEVICE_ID)
            info = parse_device_id(frame.data)
            self.state.device_id = info.device_id
            self.state.sn = info.sn
            _LOGGER.info("CTW3 id=%d sn=%s", info.device_id, info.sn)

            # 2. Security check (cmd 86)
            frame = await self._request(
                CMD_SECURITY_CHECK,
                build_security_check(self._secret),
            )
            if not frame.data or frame.data[0] != 1:
                raise CTW3AuthError("security check failed (wrong secret?)")

            # 3. Time sync (cmd 84)
            await self._request(CMD_SYNC_TIME, build_sync_time_payload())

            # 4. Firmware / hardware (cmd 200)
            frame = await self._request(CMD_GET_FIRMWARE)
            fw = parse_firmware(frame.data)
            self.state.hardware = fw.hardware
            self.state.firmware = fw.firmware

            # 5. Device log (cmd 201) — optional
            try:
                frame = await self._request(CMD_GET_DEVICE_LOG, timeout=3.0)
                self.state.device_log = parse_device_log(frame.data)
            except CTW3Timeout:
                _LOGGER.debug("Device did not respond to cmd 201 (not fatal)")

            # 6. Battery + running + settings + schedules
            await self._refresh_all_unlocked()

    # ------------------------------------------------------------------
    # High-level data refresh
    # ------------------------------------------------------------------
    async def refresh_all(self) -> CTW3State:
        async with self._operation_lock:
            return await self._refresh_all_unlocked()

    async def _refresh_all_unlocked(self) -> CTW3State:
        await self.refresh_battery()
        await self.refresh_running()
        await self.refresh_settings()
        try:
            await self.refresh_light_schedule()
        except CTW3Timeout:
            _LOGGER.debug("Light schedule request timed out (ignored)")
        try:
            await self.refresh_dnd_schedule()
        except CTW3Timeout:
            _LOGGER.debug("DND schedule request timed out (ignored)")
        self._emit_state()
        return self.state

    async def refresh_battery(self) -> BatteryInfo:
        frame = await self._request(CMD_SYNC_BATTERY)
        info = parse_battery(frame.data)
        self.state.battery = info
        return info

    async def refresh_running(self) -> RunningInfo:
        frame = await self._request(CMD_RUNNING_INFO)
        info = parse_running_info(frame.data)
        self.state.running = info
        # extended packet with embedded settings at offset 30 (data len>=32)
        if len(frame.data) >= 32:
            try:
                self.state.settings = parse_settings(frame.data[30:])
            except Exception:  # noqa: BLE001
                pass
        return info

    async def refresh_settings(self) -> SettingsInfo:
        frame = await self._request(CMD_SETTINGS)
        info = parse_settings(frame.data)
        self.state.settings = info
        return info

    async def refresh_light_schedule(self) -> ScheduleInfo:
        frame = await self._request(CMD_LIGHT_SCHEDULE)
        info = parse_schedule(frame.data)
        self.state.light_schedule = info
        return info

    async def refresh_dnd_schedule(self) -> ScheduleInfo:
        frame = await self._request(CMD_DND_SCHEDULE)
        info = parse_schedule(frame.data)
        self.state.dnd_schedule = info
        return info

    # ------------------------------------------------------------------
    # Control
    # ------------------------------------------------------------------
    async def set_power(self, on: bool) -> None:
        async with self._operation_lock:
            r = self.state.running or RunningInfo()
            await self._request(
                CMD_CONTROL,
                build_control(
                    power=1 if on else 0,
                    mode=r.mode or MODE_STANDARD,
                    suspend=r.suspend_status,
                ),
                response_cmd=CMD_CONTROL,
            )
            await self.refresh_running()
            self._emit_state()

    async def set_mode(self, mode: int) -> None:
        if mode not in (MODE_STANDARD, MODE_INTERMITTENT, MODE_BATTERY):
            raise ValueError("mode must be 1 (Standard), 2 (Intermittent), or 3 (Battery)")
        async with self._operation_lock:
            await self._request(
                CMD_CONTROL,
                build_control(power=1, mode=mode, suspend=1),
                response_cmd=CMD_CONTROL,
            )
            await self.refresh_running()
            self._emit_state()

    async def set_suspend(self, suspend: bool) -> None:
        async with self._operation_lock:
            r = self.state.running or RunningInfo()
            await self._request(
                CMD_CONTROL,
                build_control(
                    power=r.power_status if r.power_status else 1,
                    mode=r.mode or MODE_STANDARD,
                    suspend=1 if suspend else 0,
                ),
                response_cmd=CMD_CONTROL,
            )
            await self.refresh_running()
            self._emit_state()

    async def set_lamp_ring(self, enabled: bool | None = None, brightness: int | None = None) -> None:
        async with self._operation_lock:
            await self._write_settings(lamp_switch=enabled, lamp_brightness=brightness)
            self._emit_state()

    async def set_dnd(self, enabled: bool) -> None:
        async with self._operation_lock:
            await self._write_settings(no_disturbing=enabled)
            self._emit_state()

    async def set_lock(self, locked: bool) -> None:
        if not self.state.supports_lock:
            raise CTW3Error("firmware does not support lock")
        async with self._operation_lock:
            await self._write_settings(is_lock=locked)
            self._emit_state()

    async def set_smart_inductive(self, enabled: bool) -> None:
        if not self.state.supports_inductive:
            raise CTW3Error("firmware does not support inductive switches")
        async with self._operation_lock:
            await self._write_settings(smart_inductive=enabled)
            self._emit_state()

    async def set_battery_inductive(self, enabled: bool) -> None:
        if not self.state.supports_inductive:
            raise CTW3Error("firmware does not support inductive switches")
        async with self._operation_lock:
            await self._write_settings(battery_inductive=enabled)
            self._emit_state()

    async def set_smart_times(
        self, working_minutes: int | None = None, sleep_minutes: int | None = None
    ) -> None:
        async with self._operation_lock:
            await self._write_settings(
                smart_working_min=working_minutes,
                smart_sleep_min=sleep_minutes,
            )
            self._emit_state()

    async def set_battery_times(
        self, working_seconds: int | None = None, sleep_seconds: int | None = None
    ) -> None:
        async with self._operation_lock:
            await self._write_settings(
                battery_working_s=working_seconds,
                battery_sleep_s=sleep_seconds,
            )
            self._emit_state()

    async def reset_filter(self) -> None:
        async with self._operation_lock:
            await self._request(CMD_RESET_FILTER, b"", response_cmd=CMD_RESET_FILTER)
            await self.refresh_running()
            self._emit_state()

    async def write_light_schedule(
        self, enabled: bool, entries: list[tuple[int, int, int]] | None = None
    ) -> None:
        async with self._operation_lock:
            await self._request(
                CMD_WRITE_LIGHT_SCHEDULE,
                build_schedule(enabled, entries),
                response_cmd=CMD_WRITE_LIGHT_SCHEDULE,
            )
            await self.refresh_light_schedule()
            self._emit_state()

    async def write_dnd_schedule(
        self, enabled: bool, entries: list[tuple[int, int, int]] | None = None
    ) -> None:
        async with self._operation_lock:
            await self._request(
                CMD_WRITE_DND_SCHEDULE,
                build_schedule(enabled, entries),
                response_cmd=CMD_WRITE_DND_SCHEDULE,
            )
            await self.refresh_dnd_schedule()
            self._emit_state()

    async def _write_settings(
        self,
        *,
        smart_working_min: int | None = None,
        smart_sleep_min: int | None = None,
        battery_working_s: int | None = None,
        battery_sleep_s: int | None = None,
        lamp_switch: bool | None = None,
        lamp_brightness: int | None = None,
        no_disturbing: bool | None = None,
        is_lock: bool | None = None,
        smart_inductive: bool | None = None,
        battery_inductive: bool | None = None,
    ) -> None:
        s = self.state.settings or SettingsInfo()

        def pick(new, current):
            return current if new is None else new

        def pick_bool(new, current):
            if new is None:
                return current
            return 1 if new else 0

        payload = build_full_settings(
            smart_working_min=pick(smart_working_min, s.smart_working_min),
            smart_sleep_min=pick(smart_sleep_min, s.smart_sleep_min),
            battery_working_s=pick(battery_working_s, s.battery_working_s),
            battery_sleep_s=pick(battery_sleep_s, s.battery_sleep_s),
            lamp_ring_switch=pick_bool(lamp_switch, s.lamp_ring_switch),
            lamp_ring_brightness=pick(lamp_brightness, s.lamp_ring_brightness),
            no_disturbing_switch=pick_bool(no_disturbing, s.no_disturbing_switch),
            is_lock=(
                pick_bool(is_lock, s.is_lock)
                if (is_lock is not None or s.is_lock is not None) and self.state.supports_lock
                else None
            ),
            smart_inductive=(
                pick_bool(smart_inductive, s.smart_inductive)
                if (smart_inductive is not None or s.smart_inductive is not None)
                and self.state.supports_inductive
                else None
            ),
            battery_inductive=(
                pick_bool(battery_inductive, s.battery_inductive)
                if (battery_inductive is not None or s.battery_inductive is not None)
                and self.state.supports_inductive
                else None
            ),
        )
        await self._request(
            CMD_FULL_SETTINGS, payload, response_cmd=CMD_FULL_SETTINGS
        )
        await self.refresh_settings()

    # ------------------------------------------------------------------
    # History streaming (cmd 212 + stream)
    # ------------------------------------------------------------------
    async def sync_history(self, mtu: int = DEFAULT_MTU) -> list[WorkDataEntry]:
        """Run the full history-stream flow (cmd 212 → stream → cmd 69)."""
        async with self._operation_lock:
            return await self._sync_history_unlocked(mtu)

    def _reset_stream_state(self) -> None:
        self._stream_buffers.clear()
        self._stream_received.clear()
        self._stream_total = 0
        self._stream_end_event.clear()
        while not self._stream_check_queue.empty():
            try:
                self._stream_check_queue.get_nowait()
            except asyncio.QueueEmpty:
                break

    async def _ack_stream_window(
        self,
        check_frame: Frame,
        combined: list[WorkDataEntry],
    ) -> None:
        total = self._stream_total or 32
        ack = build_stream_ack_bitmask(self._stream_received)
        missing = any(idx not in self._stream_received for idx in range(total))
        if not missing:
            for idx in sorted(self._stream_received):
                combined.extend(parse_work_data_stream(bytes(self._stream_buffers[idx])))
            self._stream_buffers.clear()
            self._stream_received.clear()
            self._stream_total = 0
        await self._send_frame(
            CMD_CHECK_STREAM_DATA,
            TYPE_RESPONSE,
            ack,
            sequence=check_frame.sequence,
        )

    async def _sync_history_unlocked(self, mtu: int) -> list[WorkDataEntry]:
        self._reset_stream_state()

        # 1) request history session
        await self._request(CMD_START_SYNC_HISTORY, response_cmd=CMD_START_SYNC_HISTORY)
        # 2) push stream settings (window=32, max package = mtu)
        await self._send_frame(
            CMD_SET_STREAM_SETTING,
            TYPE_REQUEST,
            build_stream_setting(32, mtu),
        )

        combined: list[WorkDataEntry] = []
        loop = asyncio.get_running_loop()
        deadline = loop.time() + 30.0

        while loop.time() < deadline:
            if self._stream_end_event.is_set() and self._stream_check_queue.empty():
                break
            timeout = min(0.5, max(0.0, deadline - loop.time()))
            if timeout == 0.0:
                break
            try:
                check_frame = await asyncio.wait_for(
                    self._stream_check_queue.get(),
                    timeout=timeout,
                )
            except asyncio.TimeoutError:
                continue
            await self._ack_stream_window(check_frame, combined)

        if self._stream_received:
            total = self._stream_total or (max(self._stream_received) + 1)
            if any(idx not in self._stream_received for idx in range(total)):
                _LOGGER.warning(
                    "History sync ended with missing stream frames: expected %d, received %s",
                    total,
                    sorted(self._stream_received),
                )
            for idx in sorted(self._stream_received):
                combined.extend(parse_work_data_stream(bytes(self._stream_buffers[idx])))

        self.state.work_history = combined
        self._emit_state()
        if self.on_work_history:
            res = self.on_work_history(combined)
            if asyncio.iscoroutine(res):
                await res
        self._reset_stream_state()
        return combined

    # ------------------------------------------------------------------
    # Emit
    # ------------------------------------------------------------------
    def _emit_state(self) -> None:
        if self.on_state_update:
            try:
                self.on_state_update(self.state)
            except Exception:  # noqa: BLE001
                _LOGGER.exception("state update callback failed")
