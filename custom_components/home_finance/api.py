"""Small typed client for the home-finance Integration API (v1).

Kept free of Home Assistant imports so it can be tested on its own. The API is
read-only, every amount is integer cents and unknown fields must be ignored, so
responses are returned as plain dictionaries and read with ``.get``.
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Any
from urllib.parse import quote, urlsplit, urlunsplit

import aiohttp

_LOGGER = logging.getLogger(__name__)

API_PATH = "/api/integrations/v1"
DEFAULT_TIMEOUT = 20

_SLUG_RE = re.compile(r"^[a-z0-9-]{1,64}$")

type JSON = dict[str, Any]


class HomeFinanceError(Exception):
    """Base error of the home-finance client."""


class HomeFinanceConnectionError(HomeFinanceError):
    """Server unreachable: timeout, DNS, TLS or a refused connection."""


class HomeFinanceResponseError(HomeFinanceError):
    """The server answered with an error status or an unreadable body."""

    def __init__(self, status: int, code: str | None, message: str | None) -> None:
        """Store the HTTP status and the API error code."""
        super().__init__(f"HTTP {status} {code or ''}: {message or ''}".strip())
        self.status = status
        self.code = code


class HomeFinanceAuthError(HomeFinanceResponseError):
    """401: token missing, unknown, revoked or expired."""


class HomeFinanceScopeError(HomeFinanceResponseError):
    """403 insufficient_scope: the token lacks the endpoint's scope."""


class HomeFinanceNotFoundError(HomeFinanceResponseError):
    """404: unknown path or slug (renamed/archived), or no data (no periods)."""


class HomeFinanceServerError(HomeFinanceResponseError):
    """5xx (for example ``db_error``) or another unexpected status."""


def normalize_base_url(url: str) -> str:
    """Return ``scheme://host[:port][/path]`` without the API path or a trailing slash.

    Accepts a pasted URL that already contains ``/api/integrations/v1`` (or one
    of its endpoints). Raises ``ValueError`` when it is not an http(s) URL.
    """
    parts = urlsplit(url.strip())
    if parts.scheme.lower() not in ("http", "https") or not parts.hostname:
        raise ValueError("not an http(s) URL")
    path = parts.path.rstrip("/")
    idx = path.find(API_PATH)
    if idx != -1:
        path = path[:idx]
    netloc = parts.netloc.rsplit("@", 1)[-1].lower()
    return urlunsplit((parts.scheme.lower(), netloc, path.rstrip("/"), "", ""))


def _check_slug(slug: str) -> str:
    if not _SLUG_RE.match(slug):
        raise HomeFinanceNotFoundError(404, "not_found", "invalid slug")
    return quote(slug, safe="")


class HomeFinanceClient:
    """Client for ``<base_url>/api/integrations/v1``."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        base_url: str,
        token: str,
        *,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> None:
        """Initialise with a shared aiohttp session."""
        self._session = session
        self._base = normalize_base_url(base_url) + API_PATH
        self._token = token
        self._timeout = aiohttp.ClientTimeout(total=timeout)

    async def _get(self, path: str) -> JSON:
        url = self._base + path
        headers = {
            "Authorization": f"Bearer {self._token}",
            "Accept": "application/json",
        }
        try:
            async with self._session.get(
                url, headers=headers, timeout=self._timeout, allow_redirects=False
            ) as resp:
                status = resp.status
                try:
                    body: Any = await resp.json(content_type=None)
                except ValueError, aiohttp.ContentTypeError:
                    body = None
        except TimeoutError as err:
            raise HomeFinanceConnectionError(f"timeout on {path}") from err
        except aiohttp.ClientError as err:
            raise HomeFinanceConnectionError(f"{type(err).__name__} on {path}") from err

        if status == 200 and isinstance(body, dict):
            _LOGGER.debug("GET %s: %s", path, body)
            return body

        code = message = None
        if isinstance(body, dict) and isinstance(body.get("error"), dict):
            code = body["error"].get("code")
            message = body["error"].get("message")
        _LOGGER.debug("GET %s: HTTP %s %s", path, status, code)
        if status == 200:
            raise HomeFinanceServerError(status, "invalid_body", "expected a JSON object")
        if status == 401:
            raise HomeFinanceAuthError(status, code, message)
        # Only trust 403/404 when the body is the API's own error: a proxy or
        # WAF page must not make a scope look withdrawn or an endpoint missing.
        if status == 403 and code == "insufficient_scope":
            raise HomeFinanceScopeError(status, code, message)
        if status == 404 and code == "not_found":
            raise HomeFinanceNotFoundError(status, code, message)
        raise HomeFinanceServerError(status, code, message)

    async def info(self) -> JSON:
        """``GET /info``: apiVersion, tokenName and scopes (any valid token)."""
        return await self._get("/info")

    async def kids(self) -> JSON:
        """``GET /kids``: all active kids plus household totals."""
        return await self._get("/kids")

    async def kid(self, slug: str) -> JSON:
        """``GET /kids/{slug}``: one kid in full detail."""
        return await self._get(f"/kids/{_check_slug(slug)}")

    async def pots(self) -> JSON:
        """``GET /pots``: all active savings pots plus household totals."""
        return await self._get("/pots")

    async def pot(self, slug: str) -> JSON:
        """``GET /pots/{slug}``: one pot in full detail."""
        return await self._get(f"/pots/{_check_slug(slug)}")

    async def current_period(self) -> JSON:
        """``GET /periods/current``: effective totals of the current month."""
        return await self._get("/periods/current")

    async def current_year(self) -> JSON:
        """``GET /years/current``: totals of the current year (zeros without data)."""
        return await self._get("/years/current")

    async def details(
        self, kind: str, slugs: list[str]
    ) -> dict[str, JSON | HomeFinanceNotFoundError]:
        """Fetch ``/{kind}/{slug}`` for every slug in parallel.

        A 404 (renamed or archived since the list was fetched) is returned in
        place of the body so the caller can rediscover; other errors propagate.
        """
        fetch = self.kid if kind == "kids" else self.pot

        async def one(slug: str) -> JSON | HomeFinanceNotFoundError:
            try:
                return await fetch(slug)
            except HomeFinanceNotFoundError as err:
                return err

        results = await asyncio.gather(*(one(slug) for slug in slugs))
        return dict(zip(slugs, results, strict=True))
