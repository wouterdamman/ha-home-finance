"""The home-finance integration: read-only balances and budget totals."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_API_TOKEN, CONF_URL, Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryError, ConfigEntryNotReady
from homeassistant.helpers import device_registry as dr, issue_registry as ir
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import HomeFinanceAuthError, HomeFinanceClient, HomeFinanceError
from .const import CONF_SCOPES, DOMAIN, SCOPES, SUPPORTED_API_VERSION, Scope
from .coordinator import (
    COORDINATORS,
    HomeFinanceCoordinator,
    KidsCoordinator,
    PotsCoordinator,
    scope_issue_id,
)

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.BINARY_SENSOR, Platform.SENSOR]


@dataclass
class HomeFinanceRuntimeData:
    """Objects that live as long as the config entry is loaded."""

    client: HomeFinanceClient
    coordinators: dict[Scope, HomeFinanceCoordinator[Any]]


type HomeFinanceConfigEntry = ConfigEntry[HomeFinanceRuntimeData]


async def async_setup_entry(hass: HomeAssistant, entry: HomeFinanceConfigEntry) -> bool:
    """Validate the token, start one coordinator per usable scope, add platforms."""
    client = HomeFinanceClient(
        async_get_clientsession(hass), entry.data[CONF_URL], entry.data[CONF_API_TOKEN]
    )
    try:
        info = await client.info()
    except HomeFinanceAuthError as err:
        raise ConfigEntryAuthFailed("token rejected (401)") from err
    except HomeFinanceError as err:
        raise ConfigEntryNotReady(str(err)) from err
    if info.get("apiVersion") != SUPPORTED_API_VERSION:
        raise ConfigEntryError(f"unsupported apiVersion {info.get('apiVersion')!r}")

    token_scopes = info.get("scopes") or []
    held = [scope for scope in SCOPES if scope in token_scopes]
    _sync_scope_issues(hass, entry, held)

    candidates = [COORDINATORS[scope](hass, entry, client) for scope in held]
    results = await asyncio.gather(
        *(c.async_config_entry_first_refresh() for c in candidates),
        return_exceptions=True,
    )
    coordinators: dict[Scope, HomeFinanceCoordinator[Any]] = {}
    for coordinator, result in zip(candidates, results, strict=True):
        if isinstance(result, ConfigEntryNotReady) and coordinator.scope_unavailable:
            continue  # 403 or missing endpoint: leave this scope out, logged once.
        if isinstance(result, BaseException):
            raise result
        coordinators[coordinator.scope] = coordinator
    if not coordinators:
        raise ConfigEntryError(
            "none of the token's scopes is usable on this server "
            "(home-finance >= 1.26.0 is required)"
        )

    entry.runtime_data = HomeFinanceRuntimeData(client, coordinators)
    async_remove_stale_devices(hass, entry)
    for coordinator in coordinators.values():
        if isinstance(coordinator, KidsCoordinator | PotsCoordinator):
            entry.async_on_unload(
                coordinator.async_add_listener(
                    lambda c=coordinator: _on_list_update(hass, entry, c)
                )
            )
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: HomeFinanceConfigEntry) -> bool:
    """Unload the platforms."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_remove_entry(hass: HomeAssistant, entry: HomeFinanceConfigEntry) -> None:
    """Drop this integration's repair issues when the entry is deleted."""
    for scope in SCOPES:
        ir.async_delete_issue(hass, DOMAIN, scope_issue_id(entry.entry_id, scope))


async def async_remove_config_entry_device(
    hass: HomeAssistant, entry: HomeFinanceConfigEntry, device: dr.DeviceEntry
) -> bool:
    """Allow deleting a device by hand only when the API no longer lists it."""
    if getattr(entry, "runtime_data", None) is None:
        return False
    valid = current_device_identifiers(entry)
    return not any(domain == DOMAIN and ident in valid for domain, ident in device.identifiers)


def device_identifier(entry: ConfigEntry, kind: str, slug: str | None = None) -> str:
    """Return the device identifier of a kid, pot or the household device."""
    return f"{entry.entry_id}_{kind}" if slug is None else f"{entry.entry_id}_{kind}_{slug}"


def current_device_identifiers(entry: HomeFinanceConfigEntry) -> set[str]:
    """Return the identifiers of every device the latest API data describes."""
    valid = {device_identifier(entry, "household")}
    # runtime_data is unset while the entry is not loaded (setup retry, unloaded).
    runtime: HomeFinanceRuntimeData | None = getattr(entry, "runtime_data", None)
    for coordinator in runtime.coordinators.values() if runtime else ():
        if isinstance(coordinator, KidsCoordinator) and coordinator.data:
            valid.update(device_identifier(entry, "kid", s) for s in coordinator.data.items)
        if isinstance(coordinator, PotsCoordinator) and coordinator.data:
            valid.update(device_identifier(entry, "pot", s) for s in coordinator.data.items)
    return valid


@callback
def async_remove_stale_devices(hass: HomeAssistant, entry: HomeFinanceConfigEntry) -> None:
    """Remove devices of kids and pots that the API no longer lists.

    Compares against the device registry, not an in-memory set, so a kid that
    was renamed or archived while Home Assistant was stopped is cleaned up too.
    Removing a device also removes its entities.
    """
    valid = current_device_identifiers(entry)
    registry = dr.async_get(hass)
    for device in dr.async_entries_for_config_entry(registry, entry.entry_id):
        if not any(domain == DOMAIN and ident in valid for domain, ident in device.identifiers):
            _LOGGER.debug("Removing stale device %s", device.name)
            registry.async_update_device(device.id, remove_config_entry_id=entry.entry_id)


@callback
def _on_list_update(
    hass: HomeAssistant, entry: HomeFinanceConfigEntry, coordinator: HomeFinanceCoordinator[Any]
) -> None:
    # Only prune on fresh data; a failed refresh keeps the previous data.
    if coordinator.last_update_success:
        async_remove_stale_devices(hass, entry)


@callback
def _sync_scope_issues(
    hass: HomeAssistant, entry: HomeFinanceConfigEntry, held: list[Scope]
) -> None:
    """Raise a repair issue per scope the configured token used to have but lost."""
    previous = entry.data.get(CONF_SCOPES, [])
    for scope in SCOPES:
        if scope in previous and scope not in held:
            _LOGGER.warning(
                "Token no longer holds scope %s; its entities are removed until a "
                "token with that scope is configured",
                scope,
            )
            ir.async_create_issue(
                hass,
                DOMAIN,
                scope_issue_id(entry.entry_id, scope),
                is_fixable=False,
                severity=ir.IssueSeverity.WARNING,
                translation_key="scope_lost",
                translation_placeholders={"scope": scope},
            )
        else:
            ir.async_delete_issue(hass, DOMAIN, scope_issue_id(entry.entry_id, scope))
