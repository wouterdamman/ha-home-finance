"""Optional live smoke test against a real home-finance server. Not part of the test suite.

Reads HF_BASE_URL and HF_TOKEN from the environment, calls /info and the list
endpoints the token's scopes allow, and prints a short summary. Never prints
the token.

    HF_BASE_URL=https://budget.app.example.com HF_TOKEN=hf_... .venv/bin/python scripts/smoke.py
"""

from __future__ import annotations

import asyncio
import importlib.util
import os
from pathlib import Path
import sys

import aiohttp

# Load api.py on its own: it has no Home Assistant imports, the package does.
_API = Path(__file__).resolve().parent.parent / "custom_components/home_finance/api.py"
_spec = importlib.util.spec_from_file_location("home_finance_api", _API)
api = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(api)
HomeFinanceClient, HomeFinanceError = api.HomeFinanceClient, api.HomeFinanceError


async def main() -> int:
    base_url = os.environ.get("HF_BASE_URL")
    token = os.environ.get("HF_TOKEN")
    if not base_url or not token:
        print("Set HF_BASE_URL and HF_TOKEN.")
        return 2

    failures = 0
    async with aiohttp.ClientSession() as session:
        client = HomeFinanceClient(session, base_url, token)

        async def check(label: str, call):
            nonlocal failures
            try:
                body = await call()
            except HomeFinanceError as err:
                failures += 1
                print(f"FAIL {label}: {type(err).__name__} {err}")
                return None
            print(f"ok   {label}")
            return body

        info = await check("GET /info", client.info)
        if info is None:
            return 1
        scopes = info.get("scopes") or []
        print(f"     apiVersion={info.get('apiVersion')} scopes={', '.join(scopes) or '-'}")

        if "kids:read" in scopes and (kids := await check("GET /kids", client.kids)):
            slugs = [k.get("slug") for k in kids.get("kids", [])]
            print(f"     {len(slugs)} kid(s), slugs: {', '.join(map(str, slugs))}")
            for slug in slugs:
                await check(f"GET /kids/{slug}", lambda s=slug: client.kid(s))
        if "pots:read" in scopes and (pots := await check("GET /pots", client.pots)):
            slugs = [p.get("slug") for p in pots.get("pots", [])]
            print(f"     {len(slugs)} pot(s), slugs: {', '.join(map(str, slugs))}")
            for slug in slugs:
                await check(f"GET /pots/{slug}", lambda s=slug: client.pot(s))
        if "periods:read" in scopes and (
            period := await check("GET /periods/current", client.current_period)
        ):
            print(f"     period {period.get('year')}-{period.get('month')} {period.get('status')}")
        if "years:read" in scopes and (
            year := await check("GET /years/current", client.current_year)
        ):
            print(f"     year {year.get('year')}")

    print("all ok" if not failures else f"{failures} failure(s)")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
