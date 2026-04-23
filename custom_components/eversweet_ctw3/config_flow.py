"""Config flow for the PetKit CTW3 integration."""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant.components.bluetooth import (
    BluetoothServiceInfoBleak,
    async_discovered_service_info,
)
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_ADDRESS
from homeassistant.helpers.device_registry import format_mac

from .const import (
    CONF_NAME,
    CONF_SECRET,
    DOMAIN,
    NAME_PREFIXES,
)

_LOGGER = logging.getLogger(__name__)


def _is_ctw3(name: str | None) -> bool:
    if not name:
        return False
    return any(name.startswith(p) for p in NAME_PREFIXES)


def _normalize_secret(value: str) -> bytes:
    """Accept hex (16 chars) with optional spaces/colons/0x-prefix; return 8 bytes."""
    s = value.strip().replace(" ", "").replace(":", "")
    if s.lower().startswith("0x"):
        s = s[2:]
    if len(s) != 16:
        raise vol.Invalid("secret must be 16 hex characters (8 bytes)")
    try:
        return bytes.fromhex(s)
    except ValueError as err:
        raise vol.Invalid("secret is not valid hex") from err


class CTW3ConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for CTW3 devices."""

    VERSION = 1

    def __init__(self) -> None:
        self._discovered: dict[str, BluetoothServiceInfoBleak] = {}
        self._selected_address: str | None = None
        self._selected_name: str | None = None

    async def async_step_bluetooth(
        self, discovery_info: BluetoothServiceInfoBleak
    ) -> ConfigFlowResult:
        """Triggered by HA bluetooth discovery."""
        if not _is_ctw3(discovery_info.name):
            return self.async_abort(reason="not_supported")
        await self.async_set_unique_id(format_mac(discovery_info.address))
        self._abort_if_unique_id_configured(updates={CONF_ADDRESS: discovery_info.address})
        self._selected_address = discovery_info.address
        self._selected_name = discovery_info.name
        self.context["title_placeholders"] = {"name": discovery_info.name}
        return await self.async_step_confirm()

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manual setup: choose from discovered devices."""
        current_ids = self._async_current_ids()
        self._discovered.clear()
        for info in async_discovered_service_info(self.hass, connectable=True):
            if not _is_ctw3(info.name):
                continue
            mac_uid = format_mac(info.address)
            if mac_uid in current_ids:
                continue
            self._discovered[info.address] = info

        if not self._discovered:
            return self.async_abort(reason="no_devices_found")

        if user_input is not None:
            self._selected_address = user_input[CONF_ADDRESS]
            self._selected_name = self._discovered[self._selected_address].name or "CTW3"
            await self.async_set_unique_id(format_mac(self._selected_address))
            self._abort_if_unique_id_configured()
            return await self.async_step_confirm()

        schema = vol.Schema(
            {
                vol.Required(CONF_ADDRESS): vol.In(
                    {
                        addr: f"{info.name} ({addr})"
                        for addr, info in self._discovered.items()
                    }
                )
            }
        )
        return self.async_show_form(step_id="user", data_schema=schema)

    async def async_step_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        assert self._selected_address is not None

        if user_input is not None:
            try:
                secret = _normalize_secret(user_input[CONF_SECRET])
            except vol.Invalid as err:
                errors[CONF_SECRET] = str(err)
            else:
                name = user_input.get(CONF_NAME) or self._selected_name or "CTW3"
                return self.async_create_entry(
                    title=name,
                    data={
                        CONF_ADDRESS: self._selected_address,
                        CONF_SECRET: secret.hex(),
                        CONF_NAME: name,
                    },
                )

        schema = vol.Schema(
            {
                vol.Required(CONF_SECRET): str,
                vol.Optional(CONF_NAME, default=self._selected_name or "CTW3"): str,
            }
        )
        return self.async_show_form(
            step_id="confirm",
            data_schema=schema,
            errors=errors,
            description_placeholders={
                "name": self._selected_name or "CTW3",
                "address": self._selected_address,
            },
        )
