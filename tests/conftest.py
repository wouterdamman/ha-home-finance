"""Shared fixtures. Example data is copied from home-finance docs/INTEGRATIONS.md."""

from __future__ import annotations

from collections.abc import Callable
import copy
import json
from pathlib import Path
import re
from typing import Any
from unittest.mock import PropertyMock, patch

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.home_finance.const import CONF_SCOPES, DOMAIN

BASE_URL = "https://budget.app.example.com"
API = f"{BASE_URL}/api/integrations/v1"
TOKEN = "hf_testtokentesttokentesttokentesttokentest"
ALL_SCOPES = ["kids:read", "pots:read", "periods:read", "years:read"]

FIXTURES = Path(__file__).parent / "fixtures"

# path -> fixture file of a fully populated v1.26.0 server
ROUTES = {
    "/info": "info",
    "/kids": "kids",
    "/kids/sam": "kid_sam",
    "/kids/noor": "kid_noor",
    "/kids/mila": "kid_mila",
    "/pots": "pots",
    "/pots/vacation": "pot_vacation",
    "/pots/new-car": "pot_new_car",
    "/pots/buffer": "pot_buffer",
    "/pots/carryover": "pot_carryover",
    "/periods/current": "periods_current",
    "/years/current": "years_current",
}


def load(name: str) -> dict[str, Any]:
    """Return a fresh copy of a fixture."""
    return json.loads((FIXTURES / f"{name}.json").read_text())


def error(code: str) -> dict[str, Any]:
    """Return an API error body."""
    return {"error": {"code": code, "message": code.replace("_", " ")}}


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Load custom_components/ in every test."""


@pytest.fixture(autouse=True)
def all_entities_enabled(request: pytest.FixtureRequest):
    """Enable every entity so value tests can read them all.

    Tests marked ``compact_defaults`` see the real default set instead.
    """
    if request.node.get_closest_marker("compact_defaults"):
        yield
        return
    with patch(
        "homeassistant.helpers.entity.Entity.entity_registry_enabled_default",
        new_callable=PropertyMock,
        return_value=True,
    ):
        yield


type Server = Callable[..., dict[str, Any]]


@pytest.fixture
def server(aioclient_mock: AiohttpClientMocker) -> Server:
    """Install the mock API. Call again with overrides to change it.

    ``overrides`` maps a path to a body (200), to ``(status, body)``, or to an
    exception instance; ``None`` removes the route (it then 404s like an
    unknown path). Returns the bodies used, so tests can mutate and re-serve.
    """

    def install(
        overrides: dict[str, Any] | None = None, *, scopes: list[str] | None = None
    ) -> dict[str, Any]:
        aioclient_mock.clear_requests()
        bodies: dict[str, Any] = {path: load(name) for path, name in ROUTES.items()}
        bodies["/info"]["scopes"] = list(ALL_SCOPES if scopes is None else scopes)
        bodies.update(overrides or {})
        for path, body in bodies.items():
            url = API + path
            if body is None:
                continue
            if isinstance(body, BaseException):
                aioclient_mock.get(url, exc=body)
            elif isinstance(body, tuple):
                aioclient_mock.get(url, status=body[0], json=body[1])
            else:
                aioclient_mock.get(url, json=copy.deepcopy(body))
        # Anything else under the API is a JSON 404, as on the real server.
        aioclient_mock.get(
            re.compile(r".*/api/integrations/v1/.*"),
            status=404,
            json=error("not_found"),
        )
        return bodies

    return install


@pytest.fixture
def config_entry() -> MockConfigEntry:
    """A config entry for the example server holding all four scopes."""
    return MockConfigEntry(
        domain=DOMAIN,
        title="Home Assistant",
        unique_id=BASE_URL,
        data={"url": BASE_URL, "api_token": TOKEN, CONF_SCOPES: list(ALL_SCOPES)},
    )
