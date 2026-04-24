"""Client behavior tests for CTW3 BLE sequencing and stream handling.

Run with: python3 custom_components/eversweet_ctw3/test_client.py
"""
from __future__ import annotations

import sys
import types
import unittest
from pathlib import Path

_PKG_DIR = Path(__file__).resolve().parent
sys.path = [entry for entry in sys.path if Path(entry or ".").resolve() != _PKG_DIR]

import asyncio
import importlib
import struct

if "eversweet_ctw3" not in sys.modules:
    pkg = types.ModuleType("eversweet_ctw3")
    pkg.__path__ = [str(_PKG_DIR)]
    sys.modules["eversweet_ctw3"] = pkg

if "bleak" not in sys.modules:
    bleak = types.ModuleType("bleak")

    class BleakClient:  # pragma: no cover - simple import stub
        pass

    bleak.BleakClient = BleakClient
    sys.modules["bleak"] = bleak

if "bleak.exc" not in sys.modules:
    bleak_exc = types.ModuleType("bleak.exc")

    class BleakError(Exception):
        pass

    bleak_exc.BleakError = BleakError
    sys.modules["bleak.exc"] = bleak_exc

if "bleak.backends" not in sys.modules:
    sys.modules["bleak.backends"] = types.ModuleType("bleak.backends")

if "bleak.backends.device" not in sys.modules:
    device_mod = types.ModuleType("bleak.backends.device")

    class BLEDevice:
        def __init__(self, address: str, name: str | None = None) -> None:
            self.address = address
            self.name = name

    device_mod.BLEDevice = BLEDevice
    sys.modules["bleak.backends.device"] = device_mod

if "bleak_retry_connector" not in sys.modules:
    connector_mod = types.ModuleType("bleak_retry_connector")

    class BleakClientWithServiceCache:
        pass

    async def establish_connection(*_args, **_kwargs):
        raise AssertionError("connection should not be used in client unit tests")

    connector_mod.BleakClientWithServiceCache = BleakClientWithServiceCache
    connector_mod.establish_connection = establish_connection
    sys.modules["bleak_retry_connector"] = connector_mod

client_mod = importlib.import_module("eversweet_ctw3.client")
const = importlib.import_module("eversweet_ctw3.const")
protocol = importlib.import_module("eversweet_ctw3.protocol")


class ClientTests(unittest.IsolatedAsyncioTestCase):
    def _make_client(self):
        device_cls = sys.modules["bleak.backends.device"].BLEDevice
        device = device_cls("AA:BB:CC:DD:EE:FF", "Petkit_CTW3")
        return client_mod.CTW3BleClient(device, b"\x00" * 8)

    async def test_first_request_sequence_starts_at_zero(self):
        client = self._make_client()
        self.assertEqual(client._next_seq(), 0)  # noqa: SLF001
        self.assertEqual(client._next_seq(), 1)  # noqa: SLF001

    async def test_dispatch_matches_pending_by_cmd_and_sequence(self):
        client = self._make_client()
        future: asyncio.Future[protocol.Frame] = asyncio.get_running_loop().create_future()
        client._pending[(const.CMD_RUNNING_INFO, 7)] = future  # noqa: SLF001

        client._dispatch_frame(  # noqa: SLF001
            protocol.Frame(
                cmd=const.CMD_RUNNING_INFO,
                type=const.TYPE_RESPONSE,
                sequence=8,
                data=b"\x00",
            )
        )
        self.assertFalse(future.done())

        client._dispatch_frame(  # noqa: SLF001
            protocol.Frame(
                cmd=const.CMD_RUNNING_INFO,
                type=const.TYPE_RESPONSE,
                sequence=7,
                data=b"\x01",
            )
        )
        self.assertTrue(future.done())
        self.assertEqual(future.result().data, b"\x01")

    async def test_device_push_acks_reuse_device_sequence(self):
        client = self._make_client()
        sends: list[tuple[int, int, int | None, bytes]] = []

        async def fake_send(
            cmd: int,
            frame_type: int,
            data: bytes,
            *,
            sequence: int | None = None,
        ) -> int:
            sends.append((cmd, frame_type, sequence, data))
            return sequence or 0

        client._send_frame = fake_send  # type: ignore[method-assign]

        client._dispatch_frame(  # noqa: SLF001
            protocol.Frame(
                cmd=const.CMD_DEVICE_UPDATE_PUSH,
                type=const.TYPE_REQUEST,
                sequence=33,
                data=b"",
            )
        )
        client._dispatch_frame(  # noqa: SLF001
            protocol.Frame(
                cmd=const.CMD_STREAM_END,
                type=const.TYPE_REQUEST,
                sequence=44,
                data=b"",
            )
        )
        await asyncio.sleep(0)

        self.assertIn(
            (const.CMD_DEVICE_UPDATE_PUSH, const.TYPE_RESPONSE, 33, b"\x01"),
            sends,
        )
        self.assertIn(
            (const.CMD_STREAM_END, const.TYPE_RESPONSE, 44, b""),
            sends,
        )

    async def test_set_mode_uses_battery_mode_payload_from_apk(self):
        client = self._make_client()
        captured: list[tuple[int, bytes, int | None]] = []

        async def fake_request(
            cmd: int,
            data: bytes = b"",
            *,
            response_cmd: int | None = None,
            timeout: float = 0.0,
        ) -> protocol.Frame:
            captured.append((cmd, data, response_cmd))
            return protocol.Frame(
                cmd=response_cmd or cmd,
                type=const.TYPE_RESPONSE,
                sequence=1,
                data=b"",
            )

        async def fake_refresh_running() -> protocol.RunningInfo:
            client.state.running = protocol.RunningInfo(mode=const.MODE_BATTERY)
            return client.state.running

        client._request = fake_request  # type: ignore[method-assign]
        client.refresh_running = fake_refresh_running  # type: ignore[method-assign]

        await client.set_mode(const.MODE_BATTERY)

        self.assertEqual(captured[0][0], const.CMD_CONTROL)
        self.assertEqual(captured[0][1], bytes([1, 1, const.MODE_BATTERY]))

    async def test_sync_history_acks_window_with_response_type_and_same_sequence(self):
        client = self._make_client()
        sends: list[tuple[int, int, int | None, bytes]] = []

        async def fake_request(
            cmd: int,
            data: bytes = b"",
            *,
            response_cmd: int | None = None,
            timeout: float = 0.0,
        ) -> protocol.Frame:
            return protocol.Frame(
                cmd=response_cmd or cmd,
                type=const.TYPE_RESPONSE,
                sequence=1,
                data=b"\x01",
            )

        async def fake_send(
            cmd: int,
            frame_type: int,
            data: bytes,
            *,
            sequence: int | None = None,
        ) -> int:
            sends.append((cmd, frame_type, sequence, data))
            return 1 if sequence is None else sequence

        client._request = fake_request  # type: ignore[method-assign]
        client._send_frame = fake_send  # type: ignore[method-assign]

        task = asyncio.create_task(client.sync_history())
        await asyncio.sleep(0)

        client._dispatch_frame(  # noqa: SLF001
            protocol.Frame(
                cmd=const.CMD_STREAM_PUSH_68,
                type=3,
                sequence=0,
                data=struct.pack(">IH", 0, 5),
                is_stream=True,
                index=0,
                total=2,
            )
        )
        client._dispatch_frame(  # noqa: SLF001
            protocol.Frame(
                cmd=const.CMD_STREAM_PUSH_68,
                type=3,
                sequence=1,
                data=struct.pack(">IH", 3600, 10),
                is_stream=True,
                index=1,
                total=2,
            )
        )
        client._dispatch_frame(  # noqa: SLF001
            protocol.Frame(
                cmd=const.CMD_CHECK_STREAM_DATA,
                type=const.TYPE_REQUEST,
                sequence=55,
                data=b"",
            )
        )
        await asyncio.sleep(0)
        client._dispatch_frame(  # noqa: SLF001
            protocol.Frame(
                cmd=const.CMD_STREAM_END,
                type=const.TYPE_REQUEST,
                sequence=56,
                data=b"",
            )
        )

        records = await task

        self.assertEqual(len(records), 2)
        self.assertIn(
            (
                const.CMD_CHECK_STREAM_DATA,
                const.TYPE_RESPONSE,
                55,
                struct.pack(">I", (1 << 31) | (1 << 30)),
            ),
            sends,
        )
        self.assertIn(
            (const.CMD_STREAM_END, const.TYPE_RESPONSE, 56, b""),
            sends,
        )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
