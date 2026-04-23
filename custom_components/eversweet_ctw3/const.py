"""Constants for the PetKit Eversweet Max Smart (CTW3) integration."""
from __future__ import annotations

from typing import Final

DOMAIN: Final = "eversweet_ctw3"

# --- GATT UUIDs (from PetkitBleParameter) ---------------------------------
SERVICE_UUID: Final = "0000aaa0-0000-1000-8000-00805f9b34fb"
DATA_CHAR_UUID: Final = "0000aaa1-0000-1000-8000-00805f9b34fb"
CONTROL_CHAR_UUID: Final = "0000aaa2-0000-1000-8000-00805f9b34fb"

DFU_SERVICE_UUID: Final = "00010203-0405-0607-0809-0a0b0c0d1912"
DFU_CONTROL_POINT_UUID: Final = "00010203-0405-0607-0809-0a0b0c0d2b12"

# --- Frame magic ---------------------------------------------------------
MAGIC_CMD: Final = bytes([0xFA, 0xFC, 0xFD])
MAGIC_STREAM: Final = bytes([0xFA, 0xFC, 0xFE])
FRAME_TAIL: Final = 0x8F

# --- Frame types ---------------------------------------------------------
TYPE_REQUEST: Final = 1
TYPE_RESPONSE: Final = 2
TYPE_NON_RESPONSE: Final = 3

# --- Commands (from PetkitBLEConsts / CTW3DataConvertor) -----------------
CMD_SYNC_BATTERY: Final = 66          # 0x42
CMD_CHECK_STREAM_DATA: Final = 67     # 0x43  phone->device bitmask ACK
CMD_STREAM_PUSH_68: Final = 68        # 0x44
CMD_STREAM_END: Final = 69            # 0x45
CMD_OTA: Final = 70                   # 0x46
CMD_INIT_DEVICE: Final = 73           # 0x49
CMD_SET_STREAM_SETTING: Final = 80    # 0x50
CMD_STREAM_PUSH_82: Final = 82        # 0x52
CMD_START_OTA: Final = 83             # 0x53
CMD_SYNC_TIME: Final = 84             # 0x54
CMD_SECURITY_CHECK: Final = 86        # 0x56
CMD_GET_FIRMWARE: Final = 200         # 0xC8
CMD_GET_DEVICE_LOG: Final = 201       # 0xC9
CMD_RUNNING_INFO: Final = 210         # 0xD2
CMD_SETTINGS: Final = 211             # 0xD3
CMD_START_SYNC_HISTORY: Final = 212   # 0xD4
CMD_GET_DEVICE_ID: Final = 213        # 0xD5
CMD_LIGHT_SCHEDULE: Final = 215       # 0xD7
CMD_DND_SCHEDULE: Final = 216         # 0xD8
CMD_CONTROL: Final = 220              # 0xDC  [power, suspend, mode]
CMD_FULL_SETTINGS: Final = 221        # 0xDD
CMD_RESET_FILTER: Final = 222         # 0xDE
CMD_WRITE_LIGHT_SCHEDULE: Final = 225 # 0xE1
CMD_WRITE_DND_SCHEDULE: Final = 226   # 0xE2
CMD_DEVICE_UPDATE_PUSH: Final = 230   # 0xE6
CMD_WRITE_SN: Final = 244             # 0xF4

# --- Time base -----------------------------------------------------------
BASE_TIME_2000_MS: Final = 946684800000  # 2000-01-01 00:00:00 UTC in ms
BASE_TIME_2000_S: Final = 946684800

# --- Scan / connect ------------------------------------------------------
SCAN_TIMEOUT: Final = 30.0
CONNECT_TIMEOUT: Final = 20.0
NOTIFICATION_TIMEOUT: Final = 8.0
DEFAULT_MTU: Final = 247

# --- Modes ---------------------------------------------------------------
MODE_STANDARD: Final = 1
MODE_INTERMITTENT: Final = 2
MODE_BATTERY: Final = 3

MODES: Final = {
    MODE_STANDARD: "standard",
    MODE_INTERMITTENT: "intermittent",
    MODE_BATTERY: "battery",
}
MODE_NAMES: Final = {v: k for k, v in MODES.items()}
# Backward-compatible alias for older automations created before mode parity.
MODE_OPTION_ALIASES: Final = {
    "smart": MODE_INTERMITTENT,
}

# --- Name prefixes -------------------------------------------------------
NAME_PREFIXES: Final = (
    "Petkit_CTW3",
    "Petkit_CTW3_2",
    "Petkit_CTW3_100",
    "Petkit_CTW3UV",
    "Petkit_CTW3UV_100",
)

# --- Firmware gates ------------------------------------------------------
FW_INDUCTIVE_SWITCH: Final = 89     # CTW3_HAS_INDUCTIVE_SWITCH_FIRMWARE
FW_LOCK_VERSION_MIN: Final = 1.35   # hardware + firmware/100 >= 1.35

# --- Config flow keys ----------------------------------------------------
CONF_ADDRESS: Final = "address"
CONF_SECRET: Final = "secret"
CONF_NAME: Final = "name"
CONF_DEVICE_ID: Final = "device_id"

# --- Defaults ------------------------------------------------------------
DEFAULT_SCAN_INTERVAL: Final = 60  # seconds
DEFAULT_SECRET_HEX: Final = "00000000000000000000000000000000"
