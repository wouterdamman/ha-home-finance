"""Diagnostics for home-finance, with the token, URL and names redacted."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_API_TOKEN, CONF_URL
from homeassistant.core import HomeAssistant

from . import HomeFinanceConfigEntry
from .coordinator import ListData

TO_REDACT = {CONF_API_TOKEN, CONF_URL, "title", "unique_id", "name", "slug", "tokenName"}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: HomeFinanceConfigEntry
) -> dict[str, Any]:
    """Return redacted entry data and the latest API data per scope."""
    scopes: dict[str, Any] = {}
    for scope, coordinator in entry.runtime_data.coordinators.items():
        data = coordinator.data
        scopes[scope] = {
            "last_update_success": coordinator.last_update_success,
            "scope_unavailable": coordinator.scope_unavailable,
            # Slugs are derived from names, so list items by position only.
            "data": (
                {"totals": data.totals, "items": list(data.items.values())}
                if isinstance(data, ListData)
                else data
            ),
        }
    return async_redact_data(
        {
            "entry": entry.as_dict(),
            "scopes": scopes,
        },
        TO_REDACT,
    )
