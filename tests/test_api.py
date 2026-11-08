"""Tests for the HA-free API client."""

from __future__ import annotations

import asyncio

import aiohttp
import pytest
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.home_finance.api import (
    HomeFinanceAuthError,
    HomeFinanceClient,
    HomeFinanceConnectionError,
    HomeFinanceNotFoundError,
    HomeFinanceScopeError,
    HomeFinanceServerError,
    normalize_base_url,
)

from .conftest import API, BASE_URL, TOKEN, error, load


def _session(aioclient_mock: AiohttpClientMocker) -> aiohttp.ClientSession:
    return aioclient_mock.create_session(asyncio.get_running_loop())


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://budget.app.example.com", BASE_URL),
        ("  https://Budget.App.Example.com/  ", BASE_URL),
        ("https://budget.app.example.com/api/integrations/v1", BASE_URL),
        ("https://budget.app.example.com/api/integrations/v1/info", BASE_URL),
        (
            "https://user@budget.app.example.com:8443/finance/",
            "https://budget.app.example.com:8443/finance",
        ),
        (
            "HTTP://home-finance.apps.svc.cluster.local",
            "http://home-finance.apps.svc.cluster.local",
        ),
    ],
)
def test_normalize_base_url(url: str, expected: str) -> None:
    assert normalize_base_url(url) == expected


@pytest.mark.parametrize("url", ["budget.app.example.com", "ftp://example.com", "https://", ""])
def test_normalize_base_url_rejects(url: str) -> None:
    with pytest.raises(ValueError, match="http"):
        normalize_base_url(url)


async def test_endpoints_send_bearer(aioclient_mock: AiohttpClientMocker) -> None:
    for path, name in {
        "/info": "info",
        "/kids": "kids",
        "/kids/sam": "kid_sam",
        "/pots": "pots",
        "/pots/vacation": "pot_vacation",
        "/periods/current": "periods_current",
        "/years/current": "years_current",
    }.items():
        aioclient_mock.get(API + path, json=load(name))
    async with _session(aioclient_mock) as session:
        client = HomeFinanceClient(session, BASE_URL, TOKEN)
        assert (await client.info())["apiVersion"] == 1
        assert (await client.kids())["totals"]["totalCents"] == 181300
        assert (await client.kid("sam"))["slug"] == "sam"
        assert (await client.pots())["totals"]["balanceCents"] == 580000
        assert (await client.pot("vacation"))["slug"] == "vacation"
        assert (await client.current_period())["month"] == 11
        assert (await client.current_year())["year"] == 2026
    for _method, _url, _data, headers in aioclient_mock.mock_calls:
        assert headers["Authorization"] == f"Bearer {TOKEN}"


@pytest.mark.parametrize(
    ("status", "body", "exc", "code"),
    [
        (401, error("unauthorized"), HomeFinanceAuthError, "unauthorized"),
        (403, error("insufficient_scope"), HomeFinanceScopeError, "insufficient_scope"),
        (404, error("not_found"), HomeFinanceNotFoundError, "not_found"),
        (500, error("db_error"), HomeFinanceServerError, "db_error"),
        (502, None, HomeFinanceServerError, None),
        (200, ["not", "an", "object"], HomeFinanceServerError, "invalid_body"),
    ],
)
async def test_error_mapping(
    aioclient_mock: AiohttpClientMocker,
    status: int,
    body: object,
    exc: type[Exception],
    code: str | None,
) -> None:
    aioclient_mock.get(API + "/kids", status=status, json=body)
    async with _session(aioclient_mock) as session:
        client = HomeFinanceClient(session, BASE_URL, TOKEN)
        with pytest.raises(exc) as info:
            await client.kids()
    assert info.value.status == status
    assert info.value.code == code
    assert TOKEN not in str(info.value)


async def test_non_json_body(aioclient_mock: AiohttpClientMocker) -> None:
    aioclient_mock.get(API + "/info", status=502, text="<html>bad gateway</html>")
    async with _session(aioclient_mock) as session:
        client = HomeFinanceClient(session, BASE_URL, TOKEN)
        with pytest.raises(HomeFinanceServerError):
            await client.info()


@pytest.mark.parametrize(
    "exc", [TimeoutError(), aiohttp.ClientConnectionError("refused"), aiohttp.ClientError()]
)
async def test_connection_errors(aioclient_mock: AiohttpClientMocker, exc: Exception) -> None:
    aioclient_mock.get(API + "/info", exc=exc)
    async with _session(aioclient_mock) as session:
        client = HomeFinanceClient(session, BASE_URL, TOKEN)
        with pytest.raises(HomeFinanceConnectionError):
            await client.info()


async def test_invalid_slug_is_not_found_without_request(
    aioclient_mock: AiohttpClientMocker,
) -> None:
    async with _session(aioclient_mock) as session:
        client = HomeFinanceClient(session, BASE_URL, TOKEN)
        with pytest.raises(HomeFinanceNotFoundError):
            await client.kid("../info")
        with pytest.raises(HomeFinanceNotFoundError):
            await client.pot("Vacation")
    assert aioclient_mock.call_count == 0


async def test_details_returns_404s(aioclient_mock: AiohttpClientMocker) -> None:
    aioclient_mock.get(API + "/kids/sam", json=load("kid_sam"))
    aioclient_mock.get(API + "/kids/noor", status=404, json=error("not_found"))
    aioclient_mock.get(API + "/pots/vacation", json=load("pot_vacation"))
    async with _session(aioclient_mock) as session:
        client = HomeFinanceClient(session, BASE_URL, TOKEN)
        kids = await client.details("kids", ["sam", "noor"])
        pots = await client.details("pots", ["vacation"])
    assert kids["sam"]["name"] == "Sam"
    assert isinstance(kids["noor"], HomeFinanceNotFoundError)
    assert pots["vacation"]["kind"] == "normal"
