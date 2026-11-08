"""Tests for the config, reauth, reconfigure and options flows."""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

from homeassistant.config_entries import SOURCE_USER
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.home_finance.const import CONF_SCOPES, DOMAIN

from .conftest import ALL_SCOPES, BASE_URL, TOKEN, Server, error, load

NEW_TOKEN = "hf_newtokennewtokennewtokennewtokennewtoken"


@pytest.fixture(autouse=True)
def no_setup():
    """Do not set up the entry after the flow; the flow alone is under test."""
    with patch("custom_components.home_finance.async_setup_entry", return_value=True):
        yield


async def _user(hass: HomeAssistant, url: str = BASE_URL, token: str = TOKEN) -> dict[str, Any]:
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"
    return await hass.config_entries.flow.async_configure(
        result["flow_id"], {"url": url, "api_token": token}
    )


async def test_user_success(hass: HomeAssistant, server: Server) -> None:
    server(scopes=["kids:read", "years:read", "future:read"])
    result = await _user(hass, url=BASE_URL + "/api/integrations/v1/", token=f" {TOKEN} ")
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Home Assistant"
    assert result["data"] == {
        "url": BASE_URL,
        "api_token": TOKEN,
        CONF_SCOPES: ["kids:read", "years:read"],
    }
    assert result["result"].unique_id == BASE_URL


async def test_user_title_falls_back_to_host(hass: HomeAssistant, server: Server) -> None:
    info = load("info")
    del info["tokenName"]
    server({"/info": info})
    result = await _user(hass)
    assert result["title"] == "budget.app.example.com"


def _info(**changes: Any) -> dict[str, Any]:
    info = load("info")
    info.update(changes)
    return info


@pytest.mark.parametrize(
    ("override", "url", "expected"),
    [
        ((401, error("unauthorized")), BASE_URL, "invalid_auth"),
        (TimeoutError(), BASE_URL, "cannot_connect"),
        ((500, error("db_error")), BASE_URL, "unknown"),
        (None, BASE_URL, "unknown"),  # no /info at all: not home-finance
        (_info(apiVersion=2), BASE_URL, "unsupported_api"),
        (_info(scopes=[]), BASE_URL, "no_scopes"),
        (_info(scopes=["other:read"]), BASE_URL, "no_scopes"),
        (_info(scopes=None), BASE_URL, "no_scopes"),
        (load("info"), "budget.app.example.com", "invalid_url"),
    ],
)
async def test_user_errors_then_recover(
    hass: HomeAssistant, server: Server, override: Any, url: str, expected: str
) -> None:
    server({"/info": override})
    result = await _user(hass, url=url)
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": expected}

    server()
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"url": BASE_URL, "api_token": TOKEN}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY


async def test_user_duplicate(
    hass: HomeAssistant, server: Server, config_entry: MockConfigEntry
) -> None:
    config_entry.add_to_hass(hass)
    server()
    result = await _user(hass, url="https://BUDGET.app.example.com/")
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_reauth(hass: HomeAssistant, server: Server, config_entry: MockConfigEntry) -> None:
    config_entry.add_to_hass(hass)
    result = await config_entry.start_reauth_flow(hass)
    assert result["step_id"] == "reauth_confirm"
    assert result["description_placeholders"]["url"] == BASE_URL

    server({"/info": (401, error("unauthorized"))})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"api_token": "hf_stillwrong"}
    )
    assert result["errors"] == {"base": "invalid_auth"}

    server(scopes=["kids:read"])
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"api_token": NEW_TOKEN}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert config_entry.data["api_token"] == NEW_TOKEN
    assert config_entry.data[CONF_SCOPES] == ["kids:read"]


async def test_reconfigure_new_host(
    hass: HomeAssistant, server: Server, config_entry: MockConfigEntry, aioclient_mock
) -> None:
    config_entry.add_to_hass(hass)
    result = await config_entry.start_reconfigure_flow(hass)
    assert result["step_id"] == "reconfigure"

    new_base = "http://home-finance.apps.svc.cluster.local"
    aioclient_mock.clear_requests()
    aioclient_mock.get(new_base + "/api/integrations/v1/info", json=load("info"))
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"url": new_base, "api_token": NEW_TOKEN}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert config_entry.data["url"] == new_base
    assert config_entry.data["api_token"] == NEW_TOKEN
    assert config_entry.unique_id == new_base


async def test_reconfigure_same_host_and_errors(
    hass: HomeAssistant, server: Server, config_entry: MockConfigEntry
) -> None:
    config_entry.add_to_hass(hass)
    result = await config_entry.start_reconfigure_flow(hass)
    server({"/info": TimeoutError()})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"url": BASE_URL, "api_token": NEW_TOKEN}
    )
    assert result["errors"] == {"base": "cannot_connect"}

    server(scopes=ALL_SCOPES)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"url": BASE_URL, "api_token": NEW_TOKEN}
    )
    assert result["reason"] == "reconfigure_successful"
    assert config_entry.data["api_token"] == NEW_TOKEN


async def test_reconfigure_to_other_entry_aborts(
    hass: HomeAssistant, server: Server, config_entry: MockConfigEntry, aioclient_mock
) -> None:
    config_entry.add_to_hass(hass)
    other = "https://other.app.example.com"
    MockConfigEntry(
        domain=DOMAIN, unique_id=other, data={"url": other, "api_token": TOKEN}
    ).add_to_hass(hass)
    aioclient_mock.get(other + "/api/integrations/v1/info", json=load("info"))
    result = await config_entry.start_reconfigure_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"url": other, "api_token": TOKEN}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
    assert config_entry.data["url"] == BASE_URL


async def test_options_flow(hass: HomeAssistant, config_entry: MockConfigEntry) -> None:
    config_entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(config_entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    schema = result["data_schema"].schema
    default = next(k for k in schema if k == "scan_interval").default()
    assert default == 15
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"scan_interval": 30.0}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert config_entry.options == {"scan_interval": 30}
