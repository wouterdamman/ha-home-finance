"""Base entity and value helpers for home-finance."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from datetime import date
from decimal import Decimal
from typing import Any

from homeassistant.const import CONF_URL
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity import EntityDescription
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from . import HomeFinanceConfigEntry, device_identifier
from .api import JSON
from .const import (
    CONF_HOUSEHOLD_NAME,
    DEFAULT_ENABLED,
    DEFAULT_HOUSEHOLD_NAME,
    DOMAIN,
    MANUFACTURER,
    Scope,
)
from .coordinator import HomeFinanceCoordinator, ListData

KIND_KID = "kid"
KIND_POT = "pot"
KIND_HOUSEHOLD = "household"


def dig(item: JSON, *path: str) -> Any:
    """Return ``item[path[0]][path[1]]...`` or ``None`` when any level is missing."""
    value: Any = item
    for key in path:
        if not isinstance(value, dict):
            return None
        value = value.get(key)
    return value


def cents(*path: str) -> Callable[[JSON], Decimal | None]:
    """Value function: integer cents at ``path`` as euros; null stays unknown."""

    def value(item: JSON) -> Decimal | None:
        raw = dig(item, *path)
        if isinstance(raw, bool) or not isinstance(raw, int | float):
            return None
        return Decimal(str(raw)) / 100

    return value


def number(*path: str) -> Callable[[JSON], int | float | None]:
    """Value function: a plain number (percent, months, counts)."""

    def value(item: JSON) -> int | float | None:
        raw = dig(item, *path)
        if isinstance(raw, bool) or not isinstance(raw, int | float):
            return None
        return raw

    return value


def day(*path: str) -> Callable[[JSON], date | None]:
    """Value function: a ``YYYY-MM-DD`` string as a date."""

    def value(item: JSON) -> date | None:
        raw = dig(item, *path)
        return dt_util.parse_date(raw) if isinstance(raw, str) else None

    return value


def euros(raw: Any) -> float | None:
    """Cents as a float euro amount for state attributes."""
    if isinstance(raw, bool) or not isinstance(raw, int | float):
        return None
    return raw / 100


def item_getter(kind: str, slug: str | None) -> Callable[[Any], JSON | None]:
    """Return how an entity finds its object in the coordinator data.

    Kids and pots read their detail by slug; household entities read the
    ``totals`` of a list endpoint or the whole period/year body.
    """

    def get(data: Any) -> JSON | None:
        if isinstance(data, ListData):
            return data.totals if slug is None else data.items.get(slug)
        return data if isinstance(data, dict) else None

    return get


class HomeFinanceEntity(CoordinatorEntity[HomeFinanceCoordinator[Any]]):
    """An entity on a kid, pot or household device."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: HomeFinanceCoordinator[Any],
        entry: HomeFinanceConfigEntry,
        description: EntityDescription,
        kind: str,
        slug: str | None = None,
    ) -> None:
        """Bind the entity to its device and data."""
        super().__init__(coordinator)
        self.entity_description = description
        self._get_item = item_getter(kind, slug)
        ident = device_identifier(entry, kind, slug)
        self._attr_unique_id = f"{ident}_{description.key}"
        item = self.item or {}
        if kind == KIND_HOUSEHOLD:
            name = entry.data.get(CONF_HOUSEHOLD_NAME) or DEFAULT_HOUSEHOLD_NAME
            model = "Household"
        elif kind == KIND_KID:
            name, model = item.get("name") or slug, "Kid"
        else:
            name = item.get("name") or slug
            model = "Carryover pot" if item.get("kind") == "carryover" else "Savings pot"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, ident)},
            name=name,
            manufacturer=MANUFACTURER,
            model=model,
            entry_type=DeviceEntryType.SERVICE,
            configuration_url=entry.data[CONF_URL],
        )

    @property
    def item(self) -> JSON | None:
        """The kid, pot, totals or period object this entity reads."""
        return self._get_item(self.coordinator.data)

    @property
    def available(self) -> bool:
        """Unavailable when the refresh failed or the object is gone."""
        return super().available and self.item is not None


def with_default_enabled[D: EntityDescription](kind: str, descs: tuple[D, ...]) -> tuple[D, ...]:
    """Enable by default only the compact set in ``DEFAULT_ENABLED`` for this kind."""
    return tuple(
        replace(d, entity_registry_enabled_default=d.key in DEFAULT_ENABLED[kind]) for d in descs
    )


def has_target(item: JSON) -> bool:
    """Return whether the pot has a savings goal."""
    return isinstance(item.get("target"), dict)


def has_target_date(item: JSON) -> bool:
    """Return whether the pot's savings goal has a date."""
    return isinstance(dig(item, "target", "targetDate"), str)


def has_split(item: JSON) -> bool:
    """Return whether the pot ever had a share of the monthly surplus."""
    return isinstance(item.get("split"), dict)


def _exists(description: EntityDescription, item: JSON) -> bool:
    exists_fn: Callable[[JSON], bool] | None = getattr(description, "exists_fn", None)
    return exists_fn is None or exists_fn(item)


@callback
def _remove_entity(
    hass: HomeAssistant, platform: str, entry: HomeFinanceConfigEntry, ident: str, key: str
) -> None:
    registry = er.async_get(hass)
    if entity_id := registry.async_get_entity_id(platform, DOMAIN, f"{ident}_{key}"):
        registry.async_remove(entity_id)


def async_setup_entities(
    hass: HomeAssistant,
    entry: HomeFinanceConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
    *,
    platform: str,
    entity_cls: type[HomeFinanceEntity],
    descriptions: dict[tuple[Scope, str], tuple[EntityDescription, ...]],
) -> None:
    """Add household entities once and kid/pot entities as they are discovered.

    ``descriptions`` maps ``(scope, kind)`` to the descriptions for that device
    kind. New kids and pots get entities on the next refresh without a reload;
    devices that disappear are removed by ``async_remove_stale_devices``. A
    description with an ``exists_fn`` (for example a pot's savings goal) only
    gets an entity while that part of the object exists, so a pot without a goal
    has no goal sensors stuck on unknown.
    """
    for (scope, kind), descs in descriptions.items():
        coordinator = entry.runtime_data.coordinators.get(scope)
        if coordinator is None:
            if kind == KIND_HOUSEHOLD:
                # Scope unavailable at setup: drop its household entities.
                for d in descs:
                    _remove_entity(hass, platform, entry, device_identifier(entry, kind), d.key)
            continue
        if kind == KIND_HOUSEHOLD:
            async_add_entities(entity_cls(coordinator, entry, d, kind) for d in descs)
            continue

        known: set[tuple[str, str]] = set()

        @callback
        def sync(
            coordinator: HomeFinanceCoordinator[Any] = coordinator,
            kind: str = kind,
            descs: tuple[EntityDescription, ...] = descs,
            known: set[tuple[str, str]] = known,
        ) -> None:
            data = coordinator.data
            if not isinstance(data, ListData) or not coordinator.last_update_success:
                return
            wanted = [
                (slug, d) for slug, item in data.items.items() for d in descs if _exists(d, item)
            ]
            current = {(slug, d.key) for slug, d in wanted}
            for slug, key in known - current:
                # Gone with its kid/pot (device removal covers it) or, for an
                # existing pot, its goal or split was removed in the app.
                _remove_entity(hass, platform, entry, device_identifier(entry, kind, slug), key)
            new = [(slug, d) for slug, d in wanted if (slug, d.key) not in known]
            known.clear()
            known.update(current)
            async_add_entities(entity_cls(coordinator, entry, d, kind, slug) for slug, d in new)

        sync()
        entry.async_on_unload(coordinator.async_add_listener(sync))
