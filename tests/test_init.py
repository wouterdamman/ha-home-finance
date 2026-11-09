"""Tests for setup, entities, dynamic devices and runtime error handling."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from homeassistant.config_entries import SOURCE_REAUTH, ConfigEntryState
from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr, entity_registry as er, issue_registry as ir
from homeassistant.setup import async_setup_component
from homeassistant.util import dt as dt_util
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_time_changed
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMockResponse
from yarl import URL

from custom_components.home_finance import async_remove_config_entry_device
from custom_components.home_finance.const import CONF_SCOPES, DOMAIN

from .conftest import API, TOKEN, Server, error, load


async def _setup(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


async def _refresh(hass: HomeAssistant, minutes: int = 16) -> None:
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(minutes=minutes))
    await hass.async_block_till_done(wait_background_tasks=True)


def _state(hass: HomeAssistant, entity_id: str) -> str:
    state = hass.states.get(entity_id)
    assert state is not None, entity_id
    return state.state


def _devices(hass: HomeAssistant, entry: MockConfigEntry) -> set[str]:
    registry = dr.async_get(hass)
    return {d.name for d in dr.async_entries_for_config_entry(registry, entry.entry_id)}


def _issues(hass: HomeAssistant) -> set[str]:
    return {issue_id for (domain, issue_id) in ir.async_get(hass).issues if domain == DOMAIN}


async def test_full_setup(
    hass: HomeAssistant, server: Server, config_entry: MockConfigEntry
) -> None:
    server()
    await _setup(hass, config_entry)
    assert config_entry.state is ConfigEntryState.LOADED
    assert _devices(hass, config_entry) == {
        "Household",
        "Sam",
        "Noor",
        "Mila",
        "Vacation",
        "New car",
        "Buffer",
        "Carryover",
    }

    # Kids: cents become euros.
    assert _state(hass, "sensor.sam_total") == "1040"
    assert _state(hass, "sensor.sam_saved_by_us") == "875"
    assert _state(hass, "sensor.sam_own_money") == "165"
    assert _state(hass, "sensor.sam_net_this_month") == "30"
    assert _state(hass, "sensor.sam_net_this_year") == "30"
    assert _state(hass, "sensor.sam_deposited_this_month") == "30"
    assert _state(hass, "sensor.sam_deposited_this_year") == "65"
    assert _state(hass, "sensor.sam_bank_balance") == "1035"
    assert _state(hass, "sensor.sam_bank_difference") == "5"
    assert _state(hass, "sensor.sam_last_entry") == "2026-11-02"
    assert _state(hass, "sensor.sam_last_entry_amount") == "25"
    total = hass.states.get("sensor.sam_total")
    assert total.attributes["unit_of_measurement"] == "EUR"
    assert total.attributes["device_class"] == "monetary"
    assert total.attributes["state_class"] == "total"
    assert "state_class" not in hass.states.get("sensor.sam_net_this_month").attributes
    last = hass.states.get("sensor.sam_last_entry").attributes
    assert (last["type"], last["owner"], last["amount"]) == ("deposit", "ours", 25.0)
    assert hass.states.get("sensor.sam_bank_difference").attributes == {
        **hass.states.get("sensor.sam_bank_difference").attributes,
        "reported_balance_date": "2026-11-01",
    }

    # Nullable bank fields and lastEntry: unknown, not 0.
    assert _state(hass, "sensor.noor_bank_balance") == STATE_UNKNOWN
    assert _state(hass, "sensor.noor_bank_difference") == STATE_UNKNOWN
    assert _state(hass, "sensor.mila_last_entry") == STATE_UNKNOWN
    assert _state(hass, "sensor.mila_last_entry_amount") == STATE_UNKNOWN

    # Pots.
    assert _state(hass, "sensor.vacation_balance") == "1950"
    assert _state(hass, "sensor.vacation_target") == "3000"
    assert _state(hass, "sensor.vacation_progress") == "65"
    assert _state(hass, "sensor.vacation_remaining") == "1050"
    assert _state(hass, "sensor.vacation_needed_per_month") == "150"
    assert _state(hass, "sensor.vacation_months_left") == "7"
    assert _state(hass, "sensor.vacation_target_date") == "2027-06-01"
    assert _state(hass, "sensor.vacation_allocated_this_month") == "0"
    assert _state(hass, "sensor.vacation_net_this_month") == "50"
    assert _state(hass, "sensor.vacation_net_this_year") == "1100"
    assert _state(hass, "sensor.vacation_split") == "25"
    assert hass.states.get("sensor.vacation_split").attributes["period_status"] == "open"
    assert _state(hass, "sensor.vacation_last_entry") == "2026-11-02"
    assert _state(hass, "binary_sensor.vacation_goal_reached") == "off"
    # A goal without a date: goal sensors, but no date-based ones.
    assert _state(hass, "sensor.new_car_progress") == "30"
    assert hass.states.get("sensor.new_car_needed_per_month") is None
    assert hass.states.get("sensor.new_car_months_left") is None
    assert hass.states.get("sensor.new_car_target_date") is None
    # No goal and never a split: no goal or split entities at all.
    assert _state(hass, "sensor.buffer_balance") == "2500"
    for missing in (
        "sensor.buffer_target",
        "sensor.buffer_progress",
        "sensor.buffer_remaining",
        "sensor.buffer_split",
        "binary_sensor.buffer_goal_reached",
    ):
        assert hass.states.get(missing) is None, missing
    assert _state(hass, "sensor.carryover_last_entry") == "2026-11-03"
    assert hass.states.get("sensor.carryover_last_entry").attributes["amount"] == -450.0

    # Household.
    assert _state(hass, "sensor.household_kids_total") == "1813"
    assert _state(hass, "sensor.household_kids_saved_by_us") == "1598"
    assert _state(hass, "sensor.household_kids_own_money") == "215"
    assert _state(hass, "sensor.household_pots_total") == "5800"
    assert _state(hass, "sensor.household_pots_target_total") == "7000"
    assert _state(hass, "sensor.household_month_income") == "4850"
    assert _state(hass, "sensor.household_month_expenses") == "3125"
    assert _state(hass, "sensor.household_month_surplus") == "1725"
    assert _state(hass, "sensor.household_month_status") == "open"
    status = hass.states.get("sensor.household_month_status").attributes
    assert (status["year"], status["month"], status["is_current_month"]) == (2026, 11, True)
    assert _state(hass, "sensor.household_year_income") == "53100"
    assert _state(hass, "sensor.household_year_expenses") == "46887.5"
    assert _state(hass, "sensor.household_year_surplus") == "6212.5"
    assert _state(hass, "sensor.household_year_average_monthly_surplus") == "564.77"


async def test_custom_household_name(hass: HomeAssistant, server: Server) -> None:
    server()
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="https://budget.app.example.com",
        data={
            "url": "https://budget.app.example.com",
            "api_token": TOKEN,
            CONF_SCOPES: ["kids:read"],
            "household_name": "Huishouden",
        },
    )
    server(scopes=["kids:read"])
    await _setup(hass, entry)
    assert "Huishouden" in _devices(hass, entry)
    assert _state(hass, "sensor.huishouden_kids_total") == "1813"


async def test_dutch_entity_ids(hass: HomeAssistant, server: Server) -> None:
    """A Dutch install gets Dutch entity IDs (seen live on a real install)."""
    hass.config.language = "nl"
    server()
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="https://budget.app.example.com",
        data={
            "url": "https://budget.app.example.com",
            "api_token": TOKEN,
            CONF_SCOPES: ["kids:read", "pots:read"],
            "household_name": "Huishouden",
        },
    )
    server(scopes=["kids:read", "pots:read"])
    await _setup(hass, entry)
    assert _state(hass, "sensor.sam_totaal") == "1040"
    assert _state(hass, "sensor.sam_eigen_geld") == "165"
    assert _state(hass, "sensor.huishouden_kinderen_totaal") == "1813"
    assert _state(hass, "sensor.vacation_voortgang") == "65"
    assert _state(hass, "binary_sensor.vacation_spaardoel_bereikt") == "off"
    assert hass.states.get("sensor.sam_total") is None


async def test_flow_breakdowns_disabled_by_default(
    hass: HomeAssistant, server: Server, config_entry: MockConfigEntry
) -> None:
    server()
    await _setup(hass, config_entry)
    registry = er.async_get(hass)
    for entity_id in (
        "sensor.sam_opening_balance",
        "sensor.sam_total_deposits",
        "sensor.sam_own_money_net_this_month",
        "sensor.vacation_total_carried_over",
        "sensor.household_year_open_periods",
    ):
        entry = registry.async_get(entity_id)
        assert entry is not None, entity_id
        assert entry.disabled_by is er.RegistryEntryDisabler.INTEGRATION
        assert hass.states.get(entity_id) is None


async def test_unique_ids_scoped_by_kind(
    hass: HomeAssistant, server: Server, config_entry: MockConfigEntry
) -> None:
    """A kid and a pot may share a slug; their unique ids must not collide."""
    kids = load("kids")
    kids["kids"].append({"slug": "vacation", "name": "Vacation"})
    kid = load("kid_mila") | {"slug": "vacation", "name": "Vacation"}
    server({"/kids": kids, "/kids/vacation": kid})
    await _setup(hass, config_entry)
    registry = er.async_get(hass)
    kid_uid = registry.async_get("sensor.vacation_total").unique_id
    pot_uid = registry.async_get("sensor.vacation_balance").unique_id
    assert kid_uid == f"{config_entry.entry_id}_kid_vacation_total"
    assert pot_uid == f"{config_entry.entry_id}_pot_vacation_balance"


@pytest.mark.parametrize(
    ("scopes", "present", "absent"),
    [
        (
            ["kids:read"],
            ["sensor.sam_total", "sensor.household_kids_total"],
            [
                "sensor.vacation_balance",
                "sensor.household_month_income",
                "sensor.household_year_income",
            ],
        ),
        (
            ["pots:read"],
            ["sensor.vacation_balance", "binary_sensor.vacation_goal_reached"],
            ["sensor.sam_total", "sensor.household_kids_total"],
        ),
        (
            ["periods:read", "years:read"],
            ["sensor.household_month_income", "sensor.household_year_income"],
            ["sensor.sam_total", "sensor.vacation_balance"],
        ),
    ],
)
async def test_entities_per_scope(
    hass: HomeAssistant,
    server: Server,
    scopes: list[str],
    present: list[str],
    absent: list[str],
) -> None:
    server(scopes=scopes)
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="https://budget.app.example.com",
        data={"url": "https://budget.app.example.com", "api_token": TOKEN, CONF_SCOPES: scopes},
    )
    await _setup(hass, entry)
    for entity_id in present:
        assert hass.states.get(entity_id) is not None, entity_id
    for entity_id in absent:
        assert hass.states.get(entity_id) is None, entity_id
    assert not _issues(hass)


async def test_kid_and_pot_added_and_removed(
    hass: HomeAssistant, server: Server, config_entry: MockConfigEntry
) -> None:
    bodies = server()
    await _setup(hass, config_entry)

    kids = bodies["/kids"]
    kids["kids"] = [k for k in kids["kids"] if k["slug"] != "mila"]
    kids["kids"].append({"slug": "zoe", "name": "Zoë"})
    pots = bodies["/pots"]
    pots["pots"] = [p for p in pots["pots"] if p["slug"] != "buffer"]
    server(
        {
            "/kids": kids,
            "/kids/mila": None,
            "/kids/zoe": load("kid_mila") | {"slug": "zoe", "name": "Zoë", "totalCents": 1234},
            "/pots": pots,
            "/pots/buffer": None,
        }
    )
    await _refresh(hass)

    assert _state(hass, "sensor.zoe_total") == "12.34"
    assert hass.states.get("sensor.mila_total") is None
    assert hass.states.get("sensor.buffer_balance") is None
    assert er.async_get(hass).async_get("sensor.mila_total") is None
    devices = _devices(hass, config_entry)
    assert "Zoë" in devices
    assert "Mila" not in devices
    assert "Buffer" not in devices

    # Mila comes back (unarchived): her entities return without a reload.
    server()
    await _refresh(hass)
    assert _state(hass, "sensor.mila_total") == "253"
    assert "Zoë" not in _devices(hass, config_entry)


async def test_goal_added_and_removed(
    hass: HomeAssistant, server: Server, config_entry: MockConfigEntry
) -> None:
    """Goal entities follow the pot's goal without a reload."""
    server()
    await _setup(hass, config_entry)
    assert hass.states.get("sensor.buffer_progress") is None

    buffer = load("pot_buffer") | {"target": load("pot_vacation")["target"]}
    vacation = load("pot_vacation") | {"target": None}
    server({"/pots/buffer": buffer, "/pots/vacation": vacation})
    await _refresh(hass)
    assert _state(hass, "sensor.buffer_progress") == "65"
    assert _state(hass, "sensor.buffer_target_date") == "2027-06-01"
    assert _state(hass, "binary_sensor.buffer_goal_reached") == "off"
    registry = er.async_get(hass)
    assert registry.async_get("sensor.vacation_progress") is None
    assert registry.async_get("binary_sensor.vacation_goal_reached") is None
    assert _state(hass, "sensor.vacation_balance") == "1950"
    assert "Vacation" in _devices(hass, config_entry)

    # The goal comes back: same entity_id again.
    server()
    await _refresh(hass)
    assert _state(hass, "sensor.vacation_progress") == "65"
    assert hass.states.get("sensor.buffer_progress") is None


async def test_slug_change_creates_new_device(
    hass: HomeAssistant, server: Server, config_entry: MockConfigEntry
) -> None:
    bodies = server()
    await _setup(hass, config_entry)
    old_device = dr.async_get(hass).async_get_device_by_identifier(
        (DOMAIN, f"{config_entry.entry_id}_kid_sam"), config_entry.entry_id
    )
    assert old_device is not None

    # A second "Sam" appears: both slugs get the -<id> suffix.
    kids = bodies["/kids"]
    kids["kids"] = [k for k in kids["kids"] if k["slug"] != "sam"] + [
        {"slug": "sam-12", "name": "Sam"},
        {"slug": "sam-31", "name": "Sam"},
    ]
    server(
        {
            "/kids": kids,
            "/kids/sam": None,
            "/kids/sam-12": load("kid_sam") | {"slug": "sam-12"},
            "/kids/sam-31": load("kid_mila") | {"slug": "sam-31", "name": "Sam"},
        }
    )
    await _refresh(hass)
    registry = dr.async_get(hass)
    assert registry.async_get(old_device.id) is None
    assert registry.async_get_device_by_identifier(
        (DOMAIN, f"{config_entry.entry_id}_kid_sam-12"), config_entry.entry_id
    )
    assert registry.async_get_device_by_identifier(
        (DOMAIN, f"{config_entry.entry_id}_kid_sam-31"), config_entry.entry_id
    )
    # The first new "Sam" device takes over the freed entity_id.
    entity = er.async_get(hass).async_get("sensor.sam_total")
    assert entity.unique_id == f"{config_entry.entry_id}_kid_sam-12_total"


async def test_detail_404_rediscovers(
    hass: HomeAssistant, server: Server, config_entry: MockConfigEntry, aioclient_mock
) -> None:
    """Sam is renamed between the list and the detail request."""
    server()
    await _setup(hass, config_entry)

    renamed = load("kids")
    renamed["kids"][0] = {"slug": "samuel", "name": "Samuel"}
    lists = iter([load("kids"), renamed])  # first read is stale, the re-read is fresh

    async def kids_list(method, url, data):
        return AiohttpClientMockResponse(method, url, json=next(lists))

    server(
        {
            "/kids/sam": None,
            "/kids/samuel": load("kid_sam") | {"slug": "samuel", "name": "Samuel"},
        }
    )
    aioclient_mock._mocks.insert(
        0, AiohttpClientMockResponse("get", URL(API + "/kids"), side_effect=kids_list)
    )
    await _refresh(hass)
    assert _state(hass, "sensor.samuel_total") == "1040"
    assert "Sam" not in _devices(hass, config_entry)


async def test_detail_404_twice_drops_item(
    hass: HomeAssistant, server: Server, config_entry: MockConfigEntry
) -> None:
    server()
    await _setup(hass, config_entry)
    server({"/kids/noor": (404, error("not_found"))})
    await _refresh(hass)
    assert hass.states.get("sensor.noor_total") is None
    assert _state(hass, "sensor.sam_total") == "1040"


async def test_401_at_setup_starts_reauth(
    hass: HomeAssistant, server: Server, config_entry: MockConfigEntry
) -> None:
    server({"/info": (401, error("unauthorized"))})
    await _setup(hass, config_entry)
    assert config_entry.state is ConfigEntryState.SETUP_ERROR
    flows = hass.config_entries.flow.async_progress()
    assert [f["context"]["source"] for f in flows] == [SOURCE_REAUTH]


@pytest.mark.parametrize("override", [TimeoutError(), (500, error("db_error")), (503, None)])
async def test_unreachable_at_setup_retries(
    hass: HomeAssistant, server: Server, config_entry: MockConfigEntry, override: Any
) -> None:
    server({"/info": override})
    await _setup(hass, config_entry)
    assert config_entry.state is ConfigEntryState.SETUP_RETRY
    assert not hass.config_entries.flow.async_progress()


async def test_500_on_scope_at_setup_retries(
    hass: HomeAssistant, server: Server, config_entry: MockConfigEntry
) -> None:
    server({"/pots": (500, error("db_error"))})
    await _setup(hass, config_entry)
    assert config_entry.state is ConfigEntryState.SETUP_RETRY


async def test_401_on_scope_at_setup_starts_reauth(
    hass: HomeAssistant, server: Server, config_entry: MockConfigEntry
) -> None:
    server({"/years/current": (401, error("unauthorized"))})
    await _setup(hass, config_entry)
    assert config_entry.state is ConfigEntryState.SETUP_ERROR
    assert hass.config_entries.flow.async_progress()


async def test_unsupported_api_version(
    hass: HomeAssistant, server: Server, config_entry: MockConfigEntry
) -> None:
    info = load("info") | {"apiVersion": 2}
    server({"/info": info})
    await _setup(hass, config_entry)
    assert config_entry.state is ConfigEntryState.SETUP_ERROR


async def test_older_server_without_endpoints(
    hass: HomeAssistant,
    server: Server,
    config_entry: MockConfigEntry,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """v1.25.0: /info works, every list endpoint is a JSON 404."""
    server(
        {
            "/kids": None,
            "/pots": None,
            "/periods/current": None,
            "/years/current": None,
        },
        scopes=["kids:read", "pots:read"],
    )
    await _setup(hass, config_entry)
    assert config_entry.state is ConfigEntryState.SETUP_ERROR
    assert "home-finance >= 1.26.0 is required" in caplog.text


async def test_proxy_403_at_setup_retries_and_keeps_devices(
    hass: HomeAssistant, server: Server, config_entry: MockConfigEntry
) -> None:
    """A proxy 403 page is not insufficient_scope: retry, do not prune devices."""
    server()
    await _setup(hass, config_entry)
    await hass.config_entries.async_unload(config_entry.entry_id)
    server({"/pots": (403, {"detail": "forbidden by proxy"})})
    await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    assert config_entry.state is ConfigEntryState.SETUP_RETRY
    assert "Vacation" in _devices(hass, config_entry)
    assert not _issues(hass)


async def test_missing_endpoint_skips_scope(
    hass: HomeAssistant,
    server: Server,
    config_entry: MockConfigEntry,
    caplog: pytest.LogCaptureFixture,
) -> None:
    server({"/pots": None})
    await _setup(hass, config_entry)
    assert config_entry.state is ConfigEntryState.LOADED
    assert hass.states.get("sensor.vacation_balance") is None
    assert _state(hass, "sensor.sam_total") == "1040"
    assert "no endpoints for scope pots:read" in caplog.text


async def test_no_periods_yet(
    hass: HomeAssistant, server: Server, config_entry: MockConfigEntry
) -> None:
    server({"/periods/current": (404, error("not_found"))})
    await _setup(hass, config_entry)
    assert config_entry.state is ConfigEntryState.LOADED
    assert _state(hass, "sensor.household_month_income") == STATE_UNAVAILABLE
    assert _state(hass, "sensor.household_year_income") == "53100"


async def test_runtime_500_unavailable_without_reauth(
    hass: HomeAssistant, server: Server, config_entry: MockConfigEntry
) -> None:
    server()
    await _setup(hass, config_entry)
    server({"/kids": (500, error("db_error")), "/pots": TimeoutError()})
    await _refresh(hass)
    assert _state(hass, "sensor.sam_total") == STATE_UNAVAILABLE
    assert _state(hass, "sensor.vacation_balance") == STATE_UNAVAILABLE
    assert _state(hass, "sensor.household_year_income") == "53100"
    assert not hass.config_entries.flow.async_progress()
    assert config_entry.state is ConfigEntryState.LOADED
    # Devices are kept while the data is stale.
    assert "Sam" in _devices(hass, config_entry)

    server()
    await _refresh(hass)
    assert _state(hass, "sensor.sam_total") == "1040"


async def test_runtime_401_starts_reauth(
    hass: HomeAssistant, server: Server, config_entry: MockConfigEntry
) -> None:
    server()
    await _setup(hass, config_entry)
    server(
        {
            path: (401, error("unauthorized"))
            for path in ("/kids", "/pots", "/periods/current", "/years/current")
        }
    )
    await _refresh(hass)
    flows = hass.config_entries.flow.async_progress()
    assert flows
    assert all(f["context"]["source"] == SOURCE_REAUTH for f in flows)


async def test_runtime_scope_lost_raises_issue(
    hass: HomeAssistant,
    server: Server,
    config_entry: MockConfigEntry,
    caplog: pytest.LogCaptureFixture,
) -> None:
    server()
    await _setup(hass, config_entry)
    server({"/pots": (403, error("insufficient_scope"))})
    await _refresh(hass)
    await _refresh(hass, 32)
    assert _state(hass, "sensor.vacation_balance") == STATE_UNAVAILABLE
    assert _state(hass, "sensor.sam_total") == "1040"
    assert config_entry.state is ConfigEntryState.LOADED
    assert _issues(hass) == {f"{config_entry.entry_id}_scope_lost_pots"}
    assert caplog.text.count("no longer has scope pots:read") == 1
    assert not hass.config_entries.flow.async_progress()

    server()
    await _refresh(hass, 48)
    assert _state(hass, "sensor.vacation_balance") == "1950"
    assert not _issues(hass)


async def test_403_at_setup_skips_scope(
    hass: HomeAssistant, server: Server, config_entry: MockConfigEntry
) -> None:
    server({"/years/current": (403, error("insufficient_scope"))})
    await _setup(hass, config_entry)
    assert config_entry.state is ConfigEntryState.LOADED
    assert hass.states.get("sensor.household_year_income") is None
    assert _issues(hass) == {f"{config_entry.entry_id}_scope_lost_years"}


async def test_scope_dropped_from_token_at_setup(
    hass: HomeAssistant, server: Server, config_entry: MockConfigEntry
) -> None:
    """The configured token used to hold pots:read; after a restart it does not."""
    server()
    await _setup(hass, config_entry)
    assert "Vacation" in _devices(hass, config_entry)
    await hass.config_entries.async_unload(config_entry.entry_id)

    server(scopes=["kids:read", "periods:read", "years:read"])
    await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    assert config_entry.state is ConfigEntryState.LOADED
    assert _issues(hass) == {f"{config_entry.entry_id}_scope_lost_pots"}
    assert "Vacation" not in _devices(hass, config_entry)
    assert "Sam" in _devices(hass, config_entry)
    registry = er.async_get(hass)
    assert registry.async_get("sensor.household_pots_total") is None
    assert registry.async_get("sensor.household_kids_total") is not None


async def test_scan_interval_option(hass: HomeAssistant, server: Server, aioclient_mock) -> None:
    server()
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="https://budget.app.example.com",
        data={
            "url": "https://budget.app.example.com",
            "api_token": TOKEN,
            CONF_SCOPES: ["years:read"],
        },
        options={"scan_interval": 60},
    )
    server(scopes=["years:read"])
    await _setup(hass, entry)
    calls = aioclient_mock.call_count
    await _refresh(hass, 30)
    assert aioclient_mock.call_count == calls
    await _refresh(hass, 61)
    assert aioclient_mock.call_count == calls + 1


async def test_unload_and_remove(
    hass: HomeAssistant, server: Server, config_entry: MockConfigEntry
) -> None:
    server({"/pots": (403, error("insufficient_scope"))})
    await _setup(hass, config_entry)
    assert _issues(hass)
    assert await hass.config_entries.async_unload(config_entry.entry_id)
    assert config_entry.state is ConfigEntryState.NOT_LOADED
    await hass.config_entries.async_remove(config_entry.entry_id)
    await hass.async_block_till_done()
    assert not _issues(hass)


async def test_remove_config_entry_device(
    hass: HomeAssistant, server: Server, config_entry: MockConfigEntry
) -> None:
    server()
    await _setup(hass, config_entry)
    registry = dr.async_get(hass)
    sam = registry.async_get_device_by_identifier(
        (DOMAIN, f"{config_entry.entry_id}_kid_sam"), config_entry.entry_id
    )
    assert not await async_remove_config_entry_device(hass, config_entry, sam)
    ghost = registry.async_get_or_create(
        config_entry_id=config_entry.entry_id,
        identifiers={(DOMAIN, f"{config_entry.entry_id}_kid_ghost")},
    )
    assert await async_remove_config_entry_device(hass, config_entry, ghost)

    # Not loaded (unloaded or retrying setup): never allow, never crash.
    await hass.config_entries.async_unload(config_entry.entry_id)
    assert not await async_remove_config_entry_device(hass, config_entry, ghost)


async def test_stale_device_removed_at_startup(
    hass: HomeAssistant, server: Server, config_entry: MockConfigEntry
) -> None:
    """A kid archived while Home Assistant was stopped is cleaned up on setup."""
    config_entry.add_to_hass(hass)
    dr.async_get(hass).async_get_or_create(
        config_entry_id=config_entry.entry_id,
        identifiers={(DOMAIN, f"{config_entry.entry_id}_kid_archived")},
        name="Archived",
    )
    server()
    await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    assert "Archived" not in _devices(hass, config_entry)


async def test_diagnostics_redacted(
    hass: HomeAssistant, server: Server, config_entry: MockConfigEntry, hass_client
) -> None:
    from pytest_homeassistant_custom_component.components.diagnostics import (
        get_diagnostics_for_config_entry,
    )

    assert await async_setup_component(hass, "diagnostics", {})
    server()
    await _setup(hass, config_entry)
    result = await get_diagnostics_for_config_entry(hass, hass_client, config_entry)
    text = str(result)
    assert TOKEN not in text
    assert "budget.app.example.com" not in text
    assert "Sam" not in text
    assert "Vacation" not in text
    assert result["entry"]["data"]["api_token"] == "**REDACTED**"
    assert result["entry"]["data"]["url"] == "**REDACTED**"
    kids = result["scopes"]["kids:read"]["data"]
    assert kids["totals"]["totalCents"] == 181300
    assert kids["items"][0]["slug"] == "**REDACTED**"
    assert result["scopes"]["years:read"]["data"]["year"] == 2026
