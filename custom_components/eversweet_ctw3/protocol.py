"""PetKit CTW3 BLE protocol — frame encoder/decoder + payload builders/parsers.

All byte layouts are reverse-engineered from the decompiled APK:
* ``PetkitBleMsg`` — frame serialization
* ``BaseDataConvertor`` + ``CTW3DataConvertor`` — command payloads
* ``CTW3BleClient`` — state-machine / parser

Byte-order notes:
* Frame header length is **little-endian**.
* Many payload fields (deviceId, workTime, pump counters) are **big-endian**.
"""
from __future__ import annotations

import logging
import struct
import time
from dataclasses import dataclass, field
from typing import Iterable

from .const import (
    BASE_TIME_2000_MS,
    BASE_TIME_2000_S,
    CMD_CONTROL,
    CMD_SECURITY_CHECK,
    CMD_SYNC_TIME,
    FRAME_TAIL,
    MAGIC_CMD,
    MAGIC_STREAM,
    TYPE_NON_RESPONSE,
    TYPE_REQUEST,
    TYPE_RESPONSE,
)

_LOGGER = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Frame
# ---------------------------------------------------------------------------


@dataclass
class Frame:
    """A decoded PetKit BLE application-layer frame."""

    cmd: int
    type: int
    sequence: int
    data: bytes = b""
    # stream-only
    is_stream: bool = False
    index: int = 0
    total: int = 0

    def __repr__(self) -> str:  # pragma: no cover - debug aid
        kind = "STREAM" if self.is_stream else "CMD"
        return (
            f"Frame({kind} cmd={self.cmd} type={self.type} seq={self.sequence} "
            f"len={len(self.data)} data={self.data.hex()})"
        )


def encode_command(cmd: int, frame_type: int, sequence: int, data: bytes = b"") -> bytes:
    """Serialize a command frame: magic|cmd|type|seq|len(LE u16)|data|0x8F."""
    if len(data) > 0xFFFF:
        raise ValueError("payload too large")
    buf = bytearray()
    buf.extend(MAGIC_CMD)
    buf.append(cmd & 0xFF)
    buf.append(frame_type & 0xFF)
    buf.append(sequence & 0xFF)
    buf.append(len(data) & 0xFF)
    buf.append((len(data) >> 8) & 0xFF)
    buf.extend(data)
    buf.append(FRAME_TAIL)
    return bytes(buf)


def encode_stream(cmd: int, frame_type: int, index: int, total: int, data: bytes = b"") -> bytes:
    """Serialize a stream frame."""
    buf = bytearray()
    buf.extend(MAGIC_STREAM)
    buf.append(cmd & 0xFF)
    buf.append(frame_type & 0xFF)
    buf.append(index & 0xFF)
    buf.append(total & 0xFF)
    buf.append(len(data) & 0xFF)
    buf.append((len(data) >> 8) & 0xFF)
    buf.extend(data)
    return bytes(buf)


class FrameDecoder:
    """Stateful decoder that reassembles frames from BLE notifications.

    BLE notifications may split/concat frames. We buffer bytes and yield
    complete frames as they arrive.
    """

    def __init__(self) -> None:
        self._buf = bytearray()

    def feed(self, chunk: bytes) -> list[Frame]:
        self._buf.extend(chunk)
        frames: list[Frame] = []
        while True:
            frame, consumed = self._try_parse()
            if frame is None or consumed == 0:
                break
            del self._buf[:consumed]
            frames.append(frame)
        # drop stale garbage if buffer grows unbounded (no magic found)
        if len(self._buf) > 4096 and not self._find_magic():
            _LOGGER.warning("Dropping %d bytes of unframed data", len(self._buf))
            self._buf.clear()
        return frames

    def _find_magic(self) -> int | None:
        for i in range(len(self._buf) - 2):
            b = self._buf[i : i + 3]
            if bytes(b) == MAGIC_CMD or bytes(b) == MAGIC_STREAM:
                return i
        return None

    def _try_parse(self) -> tuple[Frame | None, int]:
        if len(self._buf) < 8:
            return None, 0
        idx = self._find_magic()
        if idx is None:
            return None, 0
        if idx > 0:
            _LOGGER.debug("Skipping %d leading non-magic bytes", idx)
            del self._buf[:idx]
        if len(self._buf) < 8:
            return None, 0
        magic = bytes(self._buf[0:3])
        cmd = self._buf[3]
        ftype = self._buf[4]
        if magic == MAGIC_CMD:
            seq = self._buf[5]
            data_len = self._buf[6] | (self._buf[7] << 8)
            total_len = 3 + 1 + 1 + 1 + 2 + data_len + 1
            if len(self._buf) < total_len:
                return None, 0
            data = bytes(self._buf[8 : 8 + data_len])
            tail = self._buf[8 + data_len]
            if tail != FRAME_TAIL:
                _LOGGER.debug(
                    "Unexpected tail 0x%02X for cmd=%d; accepting anyway", tail, cmd
                )
            return Frame(cmd=cmd, type=ftype, sequence=seq, data=data), total_len
        # MAGIC_STREAM
        index = self._buf[5]
        total = self._buf[6]
        if len(self._buf) < 9:
            return None, 0
        data_len = self._buf[7] | (self._buf[8] << 8)
        total_len = 3 + 1 + 1 + 1 + 1 + 2 + data_len
        if len(self._buf) < total_len:
            return None, 0
        data = bytes(self._buf[9 : 9 + data_len])
        return (
            Frame(
                cmd=cmd,
                type=ftype,
                sequence=index,
                data=data,
                is_stream=True,
                index=index,
                total=total,
            ),
            total_len,
        )


# ---------------------------------------------------------------------------
# Time helpers
# ---------------------------------------------------------------------------


def build_sync_time_payload(now_ms: int | None = None, tz_offset_h: int | None = None) -> bytes:
    """Build cmd 84 payload: [0x00 | int32 BE seconds-since-2000-UTC | tz(offset_h+12)].

    The APK sends UTC seconds for CTW3 (isAq=false) and tz as ``offset_h+12``.
    """
    if now_ms is None:
        now_ms = int(time.time() * 1000)
    seconds = max(0, (now_ms - BASE_TIME_2000_MS) // 1000)
    if tz_offset_h is None:
        tz_offset_h = int(round((time.localtime().tm_gmtoff) / 3600))
    tz_byte = (tz_offset_h + 12) & 0xFF
    buf = bytearray()
    buf.append(0x00)
    buf.extend(struct.pack(">I", seconds & 0xFFFFFFFF))
    buf.append(tz_byte)
    return bytes(buf)


def workdata_timestamp_to_posix(work_time_2000: int) -> int:
    """Convert stream `workTime` (seconds since 2000-01-01 UTC) to POSIX seconds."""
    return work_time_2000 + BASE_TIME_2000_S


# ---------------------------------------------------------------------------
# Payload builders
# ---------------------------------------------------------------------------


def build_security_check(secret: bytes) -> bytes:
    if len(secret) != 8:
        raise ValueError("secret must be 8 bytes (16 hex chars)")
    return bytes(secret)


def build_control(power: int, mode: int, suspend: int) -> bytes:
    """cmd 220 — NB: APK serializes as [power, suspend, mode]."""
    return bytes([power & 0xFF, suspend & 0xFF, mode & 0xFF])


def build_stream_setting(max_count: int, max_package_len: int) -> bytes:
    """cmd 80 — max parallel stream frames, MTU."""
    return struct.pack(">II", max_count & 0xFFFFFFFF, max_package_len & 0xFFFFFFFF)


def build_stream_ack_bitmask(received_indices: Iterable[int]) -> bytes:
    """cmd 67 — 32-bit bitmask, bit (31-i) set if index i received."""
    mask = 0
    for i in received_indices:
        if 0 <= i < 32:
            mask |= 1 << (31 - i)
    return struct.pack(">I", mask)


def build_full_settings(
    smart_working_min: int,
    smart_sleep_min: int,
    battery_working_s: int,
    battery_sleep_s: int,
    lamp_ring_switch: int,
    lamp_ring_brightness: int,
    no_disturbing_switch: int,
    is_lock: int | None = None,
    smart_inductive: int | None = None,
    battery_inductive: int | None = None,
) -> bytes:
    """cmd 221 — write full settings (9..12 bytes)."""
    buf = bytearray()
    buf.append(smart_working_min & 0xFF)
    buf.append(smart_sleep_min & 0xFF)
    buf.extend(struct.pack(">H", battery_working_s & 0xFFFF))
    buf.extend(struct.pack(">H", battery_sleep_s & 0xFFFF))
    buf.append(lamp_ring_switch & 0xFF)
    buf.append(lamp_ring_brightness & 0xFF)
    buf.append(no_disturbing_switch & 0xFF)
    if is_lock is not None:
        buf.append(is_lock & 0xFF)
    if smart_inductive is not None:
        buf.append(smart_inductive & 0xFF)
    if battery_inductive is not None:
        buf.append(battery_inductive & 0xFF)
    return bytes(buf)


def build_schedule(
    enabled: bool, entries: list[tuple[int, int, int]] | None = None
) -> bytes:
    """Cmd 215/216/225/226 — schedule payload.

    ``entries`` — list of (start_minutes, end_minutes, weekday_mask).
    """
    entries = entries or []
    buf = bytearray()
    buf.append(1 if enabled else 0)
    buf.append(len(entries) & 0xFF)
    buf.extend(b"\x00\x00\x00\x00")  # reserved
    for start, end, mask in entries:
        buf.extend(struct.pack(">H", start & 0xFFFF))
        buf.extend(struct.pack(">H", end & 0xFFFF))
        buf.append(mask & 0xFF)
    return bytes(buf)


# ---------------------------------------------------------------------------
# Payload parsers
# ---------------------------------------------------------------------------


@dataclass
class DeviceIdInfo:
    device_id: int
    sn: str


def parse_device_id(data: bytes) -> DeviceIdInfo:
    """cmd 213 response: [deviceId(8 BE) | sn(14 ASCII)]."""
    if len(data) < 22:
        raise ValueError(f"device_id payload too short: {len(data)}")
    dev_id = int.from_bytes(data[0:8], "big", signed=False)
    sn = data[8:22].decode("ascii", errors="replace").strip("\x00 ")
    return DeviceIdInfo(device_id=dev_id, sn=sn)


@dataclass
class BatteryInfo:
    voltage_mv: int
    percent: int


def parse_battery(data: bytes) -> BatteryInfo:
    """cmd 66 response: [voltage(2 BE) | percent(1)]."""
    if len(data) < 3:
        raise ValueError(f"battery payload too short: {len(data)}")
    v = int.from_bytes(data[0:2], "big", signed=False)
    p = data[2]
    return BatteryInfo(voltage_mv=v, percent=p)


@dataclass
class FirmwareInfo:
    hardware: int
    firmware: int


def parse_firmware(data: bytes) -> FirmwareInfo:
    """cmd 200 response: [hardware(1) | firmware(1) | ...]."""
    if len(data) < 2:
        raise ValueError(f"firmware payload too short: {len(data)}")
    return FirmwareInfo(hardware=data[0], firmware=data[1])


@dataclass
class DeviceLog:
    restart_times: int = 0
    run_time: int = 0
    pump_times: int = 0
    test_result: int = 0
    test_result_code: int = 0


def parse_device_log(data: bytes) -> DeviceLog:
    """cmd 201 response."""
    log = DeviceLog()
    if len(data) >= 4:
        log.restart_times = int.from_bytes(data[0:4], "big", signed=False)
    if len(data) >= 12:
        log.run_time = int.from_bytes(data[4:12], "big", signed=False)
    if len(data) >= 16:
        log.pump_times = int.from_bytes(data[12:16], "big", signed=False)
    if len(data) >= 23:
        log.test_result = data[22]
    if len(data) >= 24:
        log.test_result_code = data[23]
    return log


@dataclass
class RunningInfo:
    power_status: int = 0
    suspend_status: int = 0
    mode: int = 0
    electric_status: int = 0
    is_night_no_disturbing: int = 0
    breakdown_warning: int = 0
    lack_warning: int = 0
    low_battery: int = 0
    filter_warning: int = 0
    water_pump_run_time: int = 0
    filter_percent: int = 0
    run_status: int = 0
    today_pump_run_time: int = 0
    detect_status: int = 0
    supply_voltage_mv: int = 0
    battery_voltage_mv: int = 0
    battery_percent: int = 0
    module_status: int = 0


def parse_running_info(data: bytes) -> RunningInfo:
    """cmd 210 response (>=26 bytes)."""
    r = RunningInfo()
    if len(data) >= 1:
        r.power_status = data[0]
    if len(data) >= 2:
        r.suspend_status = data[1]
    if len(data) >= 3:
        r.mode = data[2]
    if len(data) >= 4:
        r.electric_status = data[3]
    if len(data) >= 5:
        r.is_night_no_disturbing = data[4]
    if len(data) >= 6:
        r.breakdown_warning = data[5]
    if len(data) >= 7:
        r.lack_warning = data[6]
    if len(data) >= 8:
        r.low_battery = data[7]
    if len(data) >= 9:
        r.filter_warning = data[8]
    if len(data) >= 13:
        r.water_pump_run_time = int.from_bytes(data[9:13], "big", signed=False)
    if len(data) >= 14:
        r.filter_percent = data[13]
    if len(data) >= 15:
        r.run_status = data[14]
    if len(data) >= 19:
        r.today_pump_run_time = int.from_bytes(data[15:19], "big", signed=False)
    if len(data) >= 20:
        r.detect_status = data[19]
    if len(data) >= 22:
        r.supply_voltage_mv = int.from_bytes(data[20:22], "big", signed=True)
    if len(data) >= 24:
        r.battery_voltage_mv = int.from_bytes(data[22:24], "big", signed=True)
    if len(data) >= 25:
        r.battery_percent = data[24]
    if len(data) >= 26:
        r.module_status = data[25]
    return r


@dataclass
class SettingsInfo:
    smart_working_min: int = 0
    smart_sleep_min: int = 0
    battery_working_s: int = 0
    battery_sleep_s: int = 0
    lamp_ring_switch: int = 0
    lamp_ring_brightness: int = 0
    no_disturbing_switch: int = 0
    is_lock: int | None = None
    smart_inductive: int | None = None
    battery_inductive: int | None = None


def parse_settings(data: bytes) -> SettingsInfo:
    """cmd 211 response: 9..12 bytes."""
    s = SettingsInfo()
    if len(data) >= 1:
        s.smart_working_min = data[0]
    if len(data) >= 2:
        s.smart_sleep_min = data[1]
    if len(data) >= 4:
        s.battery_working_s = int.from_bytes(data[2:4], "big", signed=False)
    if len(data) >= 6:
        s.battery_sleep_s = int.from_bytes(data[4:6], "big", signed=False)
    if len(data) >= 7:
        s.lamp_ring_switch = data[6]
    if len(data) >= 8:
        s.lamp_ring_brightness = data[7]
    if len(data) >= 9:
        s.no_disturbing_switch = data[8]
    if len(data) >= 10:
        s.is_lock = data[9]
    if len(data) >= 11:
        s.smart_inductive = data[10]
    if len(data) >= 12:
        s.battery_inductive = data[11]
    return s


@dataclass
class ScheduleEntry:
    start_minutes: int
    end_minutes: int
    weekday_mask: int


@dataclass
class ScheduleInfo:
    enabled: int = 0
    entries: list[ScheduleEntry] = field(default_factory=list)


def parse_schedule(data: bytes) -> ScheduleInfo:
    """cmd 215/216 response."""
    info = ScheduleInfo()
    if len(data) < 2:
        return info
    info.enabled = data[0]
    n = data[1]
    offset = 6
    for _ in range(n):
        if len(data) < offset + 5:
            break
        start = int.from_bytes(data[offset : offset + 2], "big", signed=False)
        end = int.from_bytes(data[offset + 2 : offset + 4], "big", signed=False)
        mask = data[offset + 4]
        info.entries.append(ScheduleEntry(start, end, mask))
        offset += 5
    return info


@dataclass
class WorkDataEntry:
    work_time_posix: int
    stay_time_seconds: int


def parse_work_data_stream(payload: bytes) -> list[WorkDataEntry]:
    """Stream cmd 68/82 payload: 6 bytes per record = [workTime(4 BE) | stayTime(2 BE)]."""
    out: list[WorkDataEntry] = []
    for i in range(0, len(payload) - len(payload) % 6, 6):
        wt = int.from_bytes(payload[i : i + 4], "big", signed=False)
        st = int.from_bytes(payload[i + 4 : i + 6], "big", signed=False)
        out.append(
            WorkDataEntry(
                work_time_posix=workdata_timestamp_to_posix(wt),
                stay_time_seconds=st,
            )
        )
    return out


# ---------------------------------------------------------------------------
# Re-exports / convenience
# ---------------------------------------------------------------------------


TYPE_REQUEST_ = TYPE_REQUEST
TYPE_RESPONSE_ = TYPE_RESPONSE
TYPE_NON_RESPONSE_ = TYPE_NON_RESPONSE

__all__ = [
    "BatteryInfo",
    "DeviceIdInfo",
    "DeviceLog",
    "FirmwareInfo",
    "Frame",
    "FrameDecoder",
    "RunningInfo",
    "ScheduleEntry",
    "ScheduleInfo",
    "SettingsInfo",
    "WorkDataEntry",
    "build_control",
    "build_full_settings",
    "build_schedule",
    "build_security_check",
    "build_stream_ack_bitmask",
    "build_stream_setting",
    "build_sync_time_payload",
    "encode_command",
    "encode_stream",
    "parse_battery",
    "parse_device_id",
    "parse_device_log",
    "parse_firmware",
    "parse_running_info",
    "parse_schedule",
    "parse_settings",
    "parse_work_data_stream",
    "workdata_timestamp_to_posix",
]
