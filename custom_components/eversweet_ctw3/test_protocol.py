"""Protocol round-trip tests — verify byte layouts against decompiled APK references.

Run with: python3 custom_components/eversweet_ctw3/test_protocol.py
"""
from __future__ import annotations

import struct
import sys
import types
import unittest
from pathlib import Path

# Build a fake `eversweet_ctw3` package so submodules resolve their
# relative imports without executing __init__.py (which pulls Home Assistant).
_PKG_DIR = Path(__file__).resolve().parent
sys.path = [entry for entry in sys.path if Path(entry or ".").resolve() != _PKG_DIR]
if "eversweet_ctw3" not in sys.modules:
    pkg = types.ModuleType("eversweet_ctw3")
    pkg.__path__ = [str(_PKG_DIR)]
    sys.modules["eversweet_ctw3"] = pkg

import importlib  # noqa: E402

protocol = importlib.import_module("eversweet_ctw3.protocol")
const = importlib.import_module("eversweet_ctw3.const")

FRAME_TAIL = const.FRAME_TAIL
MAGIC_CMD = const.MAGIC_CMD
MAGIC_STREAM = const.MAGIC_STREAM
TYPE_REQUEST = const.TYPE_REQUEST
TYPE_RESPONSE = const.TYPE_RESPONSE


class FrameTests(unittest.TestCase):
    def test_encode_command_has_correct_layout(self):
        """Matches PetkitBleMsg.toRawDataBytes: magic|cmd|type|seq|len(LE)|data|0xFB."""
        raw = protocol.encode_command(cmd=213, frame_type=TYPE_REQUEST, sequence=5, data=b"\x01\x02\x03")
        self.assertEqual(raw[0:3], MAGIC_CMD)
        self.assertEqual(raw[3], 213)
        self.assertEqual(raw[4], TYPE_REQUEST)
        self.assertEqual(raw[5], 5)
        # length little-endian
        self.assertEqual(raw[6], 3)
        self.assertEqual(raw[7], 0)
        self.assertEqual(raw[8:11], b"\x01\x02\x03")
        self.assertEqual(raw[11], FRAME_TAIL)

    def test_encode_command_matches_first_launch_capture(self):
        raw = protocol.encode_command(cmd=213, frame_type=TYPE_REQUEST, sequence=0, data=b"")
        self.assertEqual(raw, bytes.fromhex("fafcfdd501000000fb"))

    def test_length_is_little_endian_for_256(self):
        payload = b"\x00" * 256
        raw = protocol.encode_command(66, TYPE_REQUEST, 0, payload)
        # len=256 -> low=0x00 high=0x01
        self.assertEqual(raw[6], 0x00)
        self.assertEqual(raw[7], 0x01)

    def test_decoder_roundtrip(self):
        raw = protocol.encode_command(210, TYPE_RESPONSE, 9, bytes(range(26)))
        dec = protocol.FrameDecoder()
        frames = dec.feed(raw)
        self.assertEqual(len(frames), 1)
        f = frames[0]
        self.assertEqual(f.cmd, 210)
        self.assertEqual(f.type, TYPE_RESPONSE)
        self.assertEqual(f.sequence, 9)
        self.assertEqual(f.data, bytes(range(26)))
        self.assertFalse(f.is_stream)

    def test_decoder_handles_fragmented_input(self):
        raw = protocol.encode_command(66, TYPE_RESPONSE, 1, b"\xE8\x03\x64")  # 1000mV, 100%
        dec = protocol.FrameDecoder()
        frames = dec.feed(raw[:5])
        self.assertEqual(frames, [])
        frames = dec.feed(raw[5:])
        self.assertEqual(len(frames), 1)

    def test_decoder_handles_back_to_back_frames(self):
        a = protocol.encode_command(200, TYPE_RESPONSE, 1, b"\x01\x59")
        b = protocol.encode_command(66, TYPE_RESPONSE, 2, b"\xE8\x03\x64")
        dec = protocol.FrameDecoder()
        frames = dec.feed(a + b)
        self.assertEqual([x.cmd for x in frames], [200, 66])

    def test_decoder_parses_stream_frame(self):
        raw = protocol.encode_stream(cmd=68, frame_type=3, index=0, total=32, data=b"A" * 6)
        self.assertEqual(raw[0:3], MAGIC_STREAM)
        dec = protocol.FrameDecoder()
        frames = dec.feed(raw)
        self.assertEqual(len(frames), 1)
        self.assertTrue(frames[0].is_stream)
        self.assertEqual(frames[0].cmd, 68)
        self.assertEqual(frames[0].index, 0)
        self.assertEqual(frames[0].total, 32)


class PayloadTests(unittest.TestCase):
    def test_sync_time_is_2000_based_utc(self):
        # 2000-01-01 00:00:00 UTC in ms
        payload = protocol.build_sync_time_payload(now_ms=946684800000, tz_offset_h=0)
        self.assertEqual(payload[0], 0x00)
        secs = struct.unpack(">I", payload[1:5])[0]
        self.assertEqual(secs, 0)
        self.assertEqual(payload[5], 12)  # 0+12

    def test_sync_time_progresses(self):
        # 60 seconds after 2000-01-01 UTC, tz +2h
        payload = protocol.build_sync_time_payload(
            now_ms=946684800000 + 60_000, tz_offset_h=2
        )
        secs = struct.unpack(">I", payload[1:5])[0]
        self.assertEqual(secs, 60)
        self.assertEqual(payload[5], 14)

    def test_build_control_order_is_power_running_mode(self):
        """cmd 220 payload: [power, running, mode]. running=1 means pump is active."""
        buf = protocol.build_control(power=1, mode=2, running=0)
        self.assertEqual(buf, bytes([1, 0, 2]))

    def test_build_full_settings_min_and_max(self):
        # minimal 9-byte variant
        buf = protocol.build_full_settings(
            smart_working_min=10,
            smart_sleep_min=20,
            battery_working_s=300,
            battery_sleep_s=3600,
            lamp_ring_switch=1,
            lamp_ring_brightness=50,
            no_disturbing_switch=0,
        )
        self.assertEqual(len(buf), 9)
        self.assertEqual(buf[0], 10)
        self.assertEqual(buf[1], 20)
        self.assertEqual(struct.unpack(">H", buf[2:4])[0], 300)
        self.assertEqual(struct.unpack(">H", buf[4:6])[0], 3600)
        self.assertEqual(buf[6], 1)
        self.assertEqual(buf[7], 50)
        self.assertEqual(buf[8], 0)

        # maximal 12-byte variant
        buf2 = protocol.build_full_settings(
            smart_working_min=10, smart_sleep_min=20,
            battery_working_s=300, battery_sleep_s=3600,
            lamp_ring_switch=1, lamp_ring_brightness=50, no_disturbing_switch=0,
            is_lock=1, smart_inductive=1, battery_inductive=0,
        )
        self.assertEqual(len(buf2), 12)
        self.assertEqual(buf2[9], 1)
        self.assertEqual(buf2[10], 1)
        self.assertEqual(buf2[11], 0)

    def test_build_schedule(self):
        buf = protocol.build_schedule(
            enabled=True,
            entries=[(60, 120, 0x7F), (600, 720, 0x1F)],
        )
        self.assertEqual(buf[0], 1)        # enabled
        self.assertEqual(buf[1], 2)        # N
        self.assertEqual(buf[2:6], b"\x00\x00\x00\x00")
        # first entry: start=60 (BE), end=120 (BE), mask=0x7F
        self.assertEqual(struct.unpack(">H", buf[6:8])[0], 60)
        self.assertEqual(struct.unpack(">H", buf[8:10])[0], 120)
        self.assertEqual(buf[10], 0x7F)
        self.assertEqual(struct.unpack(">H", buf[11:13])[0], 600)
        self.assertEqual(struct.unpack(">H", buf[13:15])[0], 720)
        self.assertEqual(buf[15], 0x1F)

    def test_stream_ack_bitmask(self):
        # APK: for each received index i, bit (31-i) is set in a 32-bit BE mask.
        mask = protocol.build_stream_ack_bitmask([0, 1, 31])
        val = struct.unpack(">I", mask)[0]
        expected = (1 << 31) | (1 << 30) | (1 << 0)
        self.assertEqual(val, expected)

    def test_stream_setting(self):
        # struct: two BE uint32
        buf = protocol.build_stream_setting(32, 247)
        self.assertEqual(struct.unpack(">II", buf), (32, 247))


class ParseTests(unittest.TestCase):
    def test_parse_device_id(self):
        raw = (0x0102030405060708).to_bytes(8, "big") + b"SN12345678ABCD"
        info = protocol.parse_device_id(raw)
        self.assertEqual(info.device_id, 0x0102030405060708)
        self.assertEqual(info.sn, "SN12345678ABCD")

    def test_parse_battery(self):
        raw = b"\x03\xE8\x64"  # 1000 mV, 100%
        b = protocol.parse_battery(raw)
        self.assertEqual(b.voltage_mv, 1000)
        self.assertEqual(b.percent, 100)

    def test_parse_firmware(self):
        fw = protocol.parse_firmware(b"\x01\x59\x00")
        self.assertEqual(fw.hardware, 1)
        self.assertEqual(fw.firmware, 89)

    def test_parse_running_info_full(self):
        # Build a 26-byte payload that exercises every offset
        # [0]power=1 [1]running=0 [2]mode=1 [3]electric=1 [4]nightDnd=0
        # [5]breakdown=0 [6]lack=1 [7]lowBatt=0 [8]filter=0
        # [9..12] waterPumpRunTime=0x0000ABCD (BE)
        # [13] filterPct=80
        # [14] runStatus=2
        # [15..18] todayPumpRunTime=1234 (BE)
        # [19] detect=1
        # [20..21] supplyV=5000 (BE signed)
        # [22..23] battV=3700 (BE signed)
        # [24] battPct=72
        # [25] module=3
        data = bytearray()
        data += bytes([1, 0, 1, 1, 0, 0, 1, 0, 0])
        data += struct.pack(">I", 0x0000ABCD)
        data += bytes([80])
        data += bytes([2])
        data += struct.pack(">I", 1234)
        data += bytes([1])
        data += struct.pack(">h", 5000)
        data += struct.pack(">h", 3700)
        data += bytes([72])
        data += bytes([3])
        r = protocol.parse_running_info(bytes(data))
        self.assertEqual(r.power_status, 1)
        self.assertEqual(r.mode, 1)
        self.assertEqual(r.electric_status, 1)
        self.assertEqual(r.lack_warning, 1)
        self.assertEqual(r.water_pump_run_time, 0x0000ABCD)
        self.assertEqual(r.filter_percent, 80)
        self.assertEqual(r.run_status, 2)
        self.assertEqual(r.today_pump_run_time, 1234)
        self.assertEqual(r.detect_status, 1)
        self.assertEqual(r.supply_voltage_mv, 5000)
        self.assertEqual(r.battery_voltage_mv, 3700)
        self.assertEqual(r.battery_percent, 72)
        self.assertEqual(r.module_status, 3)

    def test_parse_settings_variants(self):
        # Minimal 9-byte
        payload9 = bytes([10, 20]) + struct.pack(">HH", 300, 3600) + bytes([1, 50, 0])
        s = protocol.parse_settings(payload9)
        self.assertEqual(s.smart_working_min, 10)
        self.assertEqual(s.smart_sleep_min, 20)
        self.assertEqual(s.battery_working_s, 300)
        self.assertEqual(s.battery_sleep_s, 3600)
        self.assertEqual(s.lamp_ring_switch, 1)
        self.assertEqual(s.lamp_ring_brightness, 50)
        self.assertEqual(s.no_disturbing_switch, 0)
        self.assertIsNone(s.is_lock)
        self.assertIsNone(s.smart_inductive)

        # 12-byte (lock + inductive)
        payload12 = payload9 + bytes([1, 1, 0])
        s2 = protocol.parse_settings(payload12)
        self.assertEqual(s2.is_lock, 1)
        self.assertEqual(s2.smart_inductive, 1)
        self.assertEqual(s2.battery_inductive, 0)

    def test_parse_schedule(self):
        payload = (
            bytes([1, 2, 0, 0, 0, 0])
            + struct.pack(">HH", 60, 120) + bytes([0x7F])
            + struct.pack(">HH", 600, 720) + bytes([0x1F])
        )
        info = protocol.parse_schedule(payload)
        self.assertEqual(info.enabled, 1)
        self.assertEqual(len(info.entries), 2)
        self.assertEqual(info.entries[0].start_minutes, 60)
        self.assertEqual(info.entries[0].end_minutes, 120)
        self.assertEqual(info.entries[0].weekday_mask, 0x7F)
        self.assertEqual(info.entries[1].start_minutes, 600)

    def test_parse_workdata_stream(self):
        # 2 records, workTime BE uint32 (2000-based), stayTime BE uint16
        payload = (
            struct.pack(">IH", 0, 5)
            + struct.pack(">IH", 3600, 10)
        )
        records = protocol.parse_work_data_stream(payload)
        self.assertEqual(len(records), 2)
        # workTime=0 → POSIX 2000-01-01
        self.assertEqual(records[0].work_time_posix, 946684800)
        self.assertEqual(records[0].stay_time_seconds, 5)
        self.assertEqual(records[1].work_time_posix, 946684800 + 3600)
        self.assertEqual(records[1].stay_time_seconds, 10)

    def test_parse_device_log(self):
        # restart(4 BE)=7, runTime(8 BE)=0x0102030405060708, pumpTimes(4 BE)=0xDEADBEEF
        payload = bytearray()
        payload += struct.pack(">I", 7)
        payload += struct.pack(">Q", 0x0102030405060708)
        payload += struct.pack(">I", 0xDEADBEEF)
        payload += b"\x00" * 6
        payload += bytes([2, 9])  # testResult, testResultCode
        log = protocol.parse_device_log(bytes(payload))
        self.assertEqual(log.restart_times, 7)
        self.assertEqual(log.run_time, 0x0102030405060708)
        self.assertEqual(log.pump_times, 0xDEADBEEF)
        self.assertEqual(log.test_result, 2)
        self.assertEqual(log.test_result_code, 9)


class SecretTests(unittest.TestCase):
    def test_security_check_payload_is_8_bytes(self):
        ok = protocol.build_security_check(bytes.fromhex("112233445566778899"[:16]))
        self.assertEqual(len(ok), 8)
        with self.assertRaises(ValueError):
            protocol.build_security_check(b"\x00" * 7)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
