"""Config, reauth, reconfigure and options flows for home-finance."""

from __future__ import annotations

from collections.abc import Mapping
import logging
from typing import Any
from urllib.parse import urlsplit

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult, OptionsFlowWithReload
from homeassistant.const import CONF_API_TOKEN, CONF_SCAN_INTERVAL, CONF_URL
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)
import voluptuous as vol

from . import HomeFinanceConfigEntry
from .api import (
    JSON,
    HomeFinanceAuthError,
    HomeFinanceClient,
    HomeFinanceConnectionError,
    HomeFinanceError,
    normalize_base_url,
)
from .const import (
    CONF_SCOPES,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    MAX_SCAN_INTERVAL_MINUTES,
    MIN_SCAN_INTERVAL_MINUTES,
    SCOPES,
    SUPPORTED_API_VERSION,
)

_LOGGER = logging.getLogger(__name__)

URL_SELECTOR = TextSelector(TextSelectorConfig(type=TextSelectorType.URL))
TOKEN_SELECTOR = TextSelector(TextSelectorConfig(type=TextSelectorType.PASSWORD))
# hassfest forbids URLs inside translation strings, so the example is a placeholder.
URL_PLACEHOLDERS = {"example_url": "https://budget.app.example.com"}


class FlowError(Exception):
    """Validation failed; ``args[0]`` is the translated error key."""


async def _validate(flow: ConfigFlow, url: str, token: str) -> tuple[str, JSON]:
    """Return the normalised base URL and the ``/info`` body, or raise FlowError."""
    try:
        base_url = normalize_base_url(url)
    except ValueError as err:
        raise FlowError("invalid_url") from err
    client = HomeFinanceClient(async_get_clientsession(flow.hass), base_url, token.strip())
    try:
        info = await client.info()
    except HomeFinanceAuthError as err:
        raise FlowError("invalid_auth") from err
    except HomeFinanceConnectionError as err:
        raise FlowError("cannot_connect") from err
    except HomeFinanceError as err:
        _LOGGER.debug("Unexpected answer from /info: %s", err)
        raise FlowError("cannot_connect") from err
    if info.get("apiVersion") != SUPPORTED_API_VERSION:
        raise FlowError("unsupported_api")
    scopes = info.get("scopes")
    if not isinstance(scopes, list) or not any(s in scopes for s in SCOPES):
        raise FlowError("no_scopes")
    return base_url, info


def _data(base_url: str, token: str, info: JSON) -> dict[str, Any]:
    return {
        CONF_URL: base_url,
        CONF_API_TOKEN: token.strip(),
        CONF_SCOPES: [s for s in SCOPES if s in info["scopes"]],
    }


class HomeFinanceConfigFlow(ConfigFlow, domain=DOMAIN):
    """Set up a home-finance server with a base URL and an integration token."""

    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: HomeFinanceConfigEntry) -> HomeFinanceOptionsFlow:
        """Return the options flow."""
        return HomeFinanceOptionsFlow()

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Ask for the base URL and token."""
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                base_url, info = await _validate(
                    self, user_input[CONF_URL], user_input[CONF_API_TOKEN]
                )
            except FlowError as err:
                errors["base"] = err.args[0]
            else:
                await self.async_set_unique_id(base_url)
                self._abort_if_unique_id_configured()
                title = info.get("tokenName") or urlsplit(base_url).hostname or base_url
                return self.async_create_entry(
                    title=title, data=_data(base_url, user_input[CONF_API_TOKEN], info)
                )
        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(
                vol.Schema(
                    {
                        vol.Required(CONF_URL): URL_SELECTOR,
                        vol.Required(CONF_API_TOKEN): TOKEN_SELECTOR,
                    }
                ),
                {CONF_URL: (user_input or {}).get(CONF_URL)},
            ),
            description_placeholders=URL_PLACEHOLDERS,
            errors=errors,
        )

    async def async_step_reauth(self, entry_data: Mapping[str, Any]) -> ConfigFlowResult:
        """Start reauth after a rejected (expired or revoked) token."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for a new token for the same server."""
        entry = self._get_reauth_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                base_url, info = await _validate(
                    self, entry.data[CONF_URL], user_input[CONF_API_TOKEN]
                )
            except FlowError as err:
                errors["base"] = err.args[0]
            else:
                return self.async_update_reload_and_abort(
                    entry, data_updates=_data(base_url, user_input[CONF_API_TOKEN], info)
                )
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema({vol.Required(CONF_API_TOKEN): TOKEN_SELECTOR}),
            description_placeholders={"url": entry.data[CONF_URL]},
            errors=errors,
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Change the base URL and/or token."""
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                base_url, info = await _validate(
                    self, user_input[CONF_URL], user_input[CONF_API_TOKEN]
                )
            except FlowError as err:
                errors["base"] = err.args[0]
            else:
                if base_url != entry.unique_id:
                    # A new host for the same server is fine; another entry's is not.
                    await self.async_set_unique_id(base_url)
                    self._abort_if_unique_id_configured()
                return self.async_update_reload_and_abort(
                    entry,
                    unique_id=base_url,
                    data_updates=_data(base_url, user_input[CONF_API_TOKEN], info),
                )
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=self.add_suggested_values_to_schema(
                vol.Schema(
                    {
                        vol.Required(CONF_URL): URL_SELECTOR,
                        vol.Required(CONF_API_TOKEN): TOKEN_SELECTOR,
                    }
                ),
                {CONF_URL: (user_input or entry.data).get(CONF_URL)},
            ),
            description_placeholders=URL_PLACEHOLDERS,
            errors=errors,
        )


class HomeFinanceOptionsFlow(OptionsFlowWithReload):
    """Polling interval."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Ask for the scan interval in minutes."""
        if user_input is not None:
            return self.async_create_entry(
                data={CONF_SCAN_INTERVAL: int(user_input[CONF_SCAN_INTERVAL])}
            )
        current = self.config_entry.options.get(
            CONF_SCAN_INTERVAL, int(DEFAULT_SCAN_INTERVAL.total_seconds() // 60)
        )
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_SCAN_INTERVAL, default=current): NumberSelector(
                        NumberSelectorConfig(
                            min=MIN_SCAN_INTERVAL_MINUTES,
                            max=MAX_SCAN_INTERVAL_MINUTES,
                            step=1,
                            mode=NumberSelectorMode.BOX,
                            unit_of_measurement="min",
                        )
                    )
                }
            ),
        )
