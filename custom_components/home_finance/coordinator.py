"""Data update coordinators for home-finance, one per token scope.

One coordinator per scope keeps failures isolated: a 403 on ``/pots`` only makes
the pot entities unavailable, the kid and budget entities keep updating.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta
import logging
from typing import TYPE_CHECKING, Any

from homeassistant.const import CONF_SCAN_INTERVAL
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import (
    JSON,
    HomeFinanceAuthError,
    HomeFinanceClient,
    HomeFinanceError,
    HomeFinanceNotFoundError,
    HomeFinanceScopeError,
)
from .const import DEFAULT_SCAN_INTERVAL, DOMAIN, Scope

if TYPE_CHECKING:
    from . import HomeFinanceConfigEntry

_LOGGER = logging.getLogger(__package__)

# A detail 404 means the kid or pot was renamed or archived after the list was
# fetched. Re-read the list this many extra times before giving up for this round.
_REDISCOVER_ATTEMPTS = 1


@dataclass(frozen=True, slots=True)
class ListData:
    """A list endpoint's household totals plus the detail of every item, by slug."""

    totals: JSON
    items: dict[str, JSON] = field(default_factory=dict)


def scope_issue_id(entry_id: str, scope: Scope) -> str:
    """Return the repair issue id for a scope the entry's token lost."""
    return f"{entry_id}_scope_lost_{scope.split(':')[0]}"


class HomeFinanceCoordinator[DataT](DataUpdateCoordinator[DataT]):
    """Polls the endpoints of one scope and maps API errors to HA semantics."""

    config_entry: HomeFinanceConfigEntry
    scope: Scope

    def __init__(
        self,
        hass: HomeAssistant,
        entry: HomeFinanceConfigEntry,
        client: HomeFinanceClient,
    ) -> None:
        """Initialise the coordinator for ``self.scope``."""
        minutes = entry.options.get(CONF_SCAN_INTERVAL)
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{DOMAIN} {self.scope}",
            update_interval=(timedelta(minutes=minutes) if minutes else DEFAULT_SCAN_INTERVAL),
        )
        self.client = client
        # Set when the scope is unusable on this server/token (403 or a missing
        # endpoint), as opposed to a transient failure. Setup skips such scopes.
        self.scope_unavailable = False
        self._problem_logged = False

    async def _fetch(self) -> DataT:
        raise NotImplementedError

    async def _async_update_data(self) -> DataT:
        try:
            data = await self._fetch()
        except HomeFinanceAuthError as err:
            # 401: revoked, expired or unknown token. Starts the reauth flow.
            raise ConfigEntryAuthFailed("token rejected (401)") from err
        except HomeFinanceScopeError as err:
            self.scope_unavailable = True
            self._report_problem(
                "Token no longer has scope %s; its entities are unavailable until a "
                "token with that scope is configured",
            )
            ir.async_create_issue(
                self.hass,
                DOMAIN,
                scope_issue_id(self.config_entry.entry_id, self.scope),
                is_fixable=False,
                severity=ir.IssueSeverity.WARNING,
                translation_key="scope_lost",
                translation_placeholders={"scope": self.scope},
            )
            raise UpdateFailed(f"insufficient scope {self.scope}") from err
        except HomeFinanceNotFoundError as err:
            self.scope_unavailable = True
            self._report_problem(
                "The server has no endpoints for scope %s (404); home-finance "
                ">= 1.26.0 is required",
            )
            raise UpdateFailed(f"endpoint not found for {self.scope}") from err
        except HomeFinanceError as err:
            # 500 db_error, other statuses, timeouts and connection errors:
            # entities go unavailable and the next refresh retries. Never reauth.
            raise UpdateFailed(str(err)) from err

        if self.scope_unavailable:
            _LOGGER.info("Scope %s is available again", self.scope)
        self.scope_unavailable = False
        self._problem_logged = False
        ir.async_delete_issue(
            self.hass, DOMAIN, scope_issue_id(self.config_entry.entry_id, self.scope)
        )
        return data

    def _report_problem(self, message: str) -> None:
        if not self._problem_logged:
            _LOGGER.warning(message, self.scope)
            self._problem_logged = True


class _ListCoordinator(HomeFinanceCoordinator[ListData]):
    """``GET /{kind}`` then ``GET /{kind}/{slug}`` for every listed item."""

    kind: str

    async def _list(self) -> JSON:
        raise NotImplementedError

    async def _fetch(self) -> ListData:
        listing = await self._list()
        for attempt in range(_REDISCOVER_ATTEMPTS + 1):
            slugs = _slugs(listing.get(self.kind))
            details = await self.client.details(self.kind, slugs)
            missing = [s for s, d in details.items() if not isinstance(d, dict)]
            if not missing or attempt == _REDISCOVER_ATTEMPTS:
                break
            _LOGGER.debug(
                "%s %s returned 404 (renamed or archived); rediscovering",
                self.kind,
                missing,
            )
            listing = await self._list()
        totals = listing.get("totals")
        return ListData(
            totals=totals if isinstance(totals, dict) else {},
            items={s: d for s, d in details.items() if isinstance(d, dict)},
        )


def _slugs(items: Any) -> list[str]:
    if not isinstance(items, list):
        return []
    slugs: list[str] = []
    for item in items:
        slug = item.get("slug") if isinstance(item, dict) else None
        if isinstance(slug, str) and slug not in slugs:
            slugs.append(slug)
    return slugs


class KidsCoordinator(_ListCoordinator):
    """Kids, their sub-pots and the household kid totals."""

    scope = Scope.KIDS
    kind = "kids"

    async def _list(self) -> JSON:
        return await self.client.kids()


class PotsCoordinator(_ListCoordinator):
    """Savings pots and the household pot totals."""

    scope = Scope.POTS
    kind = "pots"

    async def _list(self) -> JSON:
        return await self.client.pots()


class PeriodCoordinator(HomeFinanceCoordinator[JSON | None]):
    """``GET /periods/current``; ``None`` while the app has no periods at all."""

    scope = Scope.PERIODS

    async def _fetch(self) -> JSON | None:
        try:
            return await self.client.current_period()
        except HomeFinanceNotFoundError:
            # Documented: 404 when no periods exist. Not a missing endpoint, as
            # periods:read only exists on servers that have /periods.
            _LOGGER.debug("No periods exist yet")
            return None


class YearCoordinator(HomeFinanceCoordinator[JSON]):
    """``GET /years/current`` (zeros, never 404, for a year without data)."""

    scope = Scope.YEARS

    async def _fetch(self) -> JSON:
        return await self.client.current_year()


COORDINATORS: dict[Scope, type[HomeFinanceCoordinator[Any]]] = {
    Scope.KIDS: KidsCoordinator,
    Scope.POTS: PotsCoordinator,
    Scope.PERIODS: PeriodCoordinator,
    Scope.YEARS: YearCoordinator,
}
