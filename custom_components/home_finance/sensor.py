"""Sensors for kids, savings pots and household totals."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import PERCENTAGE, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.typing import StateType

from . import HomeFinanceConfigEntry
from .api import JSON
from .const import Scope
from .entity import (
    KIND_HOUSEHOLD,
    KIND_KID,
    KIND_POT,
    HomeFinanceEntity,
    async_setup_entities,
    cents,
    day,
    dig,
    euros,
    has_split,
    has_target,
    has_target_date,
    number,
    with_default_enabled,
)

# Read-only polling through coordinators: no per-entity update concurrency.
PARALLEL_UPDATES = 0

CURRENCY = "EUR"
PERIOD_STATUSES = ["open", "closed"]


@dataclass(frozen=True, kw_only=True)
class HomeFinanceSensorEntityDescription(SensorEntityDescription):
    """A sensor description that knows how to read its value."""

    value_fn: Callable[[JSON], StateType | date | Decimal]
    attrs_fn: Callable[[JSON], dict[str, Any]] | None = None
    # When set, the entity only exists while this returns True for the object.
    exists_fn: Callable[[JSON], bool] | None = None


def _money(
    key: str,
    value_fn: Callable[[JSON], Decimal | None],
    *,
    balance: bool = False,
    attrs_fn: Callable[[JSON], dict[str, Any]] | None = None,
    exists_fn: Callable[[JSON], bool] | None = None,
) -> HomeFinanceSensorEntityDescription:
    """Describe a EUR sensor. Only real balances get ``state_class: total``.

    Month and year figures reset every period; recording them as long-term
    statistics would show misleading sums, so they have no state class.
    """
    return HomeFinanceSensorEntityDescription(
        key=key,
        translation_key=key,
        device_class=SensorDeviceClass.MONETARY,
        native_unit_of_measurement=CURRENCY,
        suggested_display_precision=2,
        state_class=SensorStateClass.TOTAL if balance else None,
        value_fn=value_fn,
        attrs_fn=attrs_fn,
        exists_fn=exists_fn,
    )


def _bank_attrs(item: JSON) -> dict[str, Any]:
    return {"reported_balance_date": dig(item, "bank", "reportedBalanceDate")}


def _kid_last_entry_attrs(item: JSON) -> dict[str, Any]:
    entry = item.get("lastEntry") or {}
    return {
        "type": entry.get("type"),
        "owner": entry.get("owner"),
        "amount": euros(entry.get("amountCents")),
    }


def _pot_last_entry_attrs(item: JSON) -> dict[str, Any]:
    entry = item.get("lastEntry") or {}
    return {"type": entry.get("type"), "amount": euros(entry.get("amountCents"))}


def _split_attrs(item: JSON) -> dict[str, Any]:
    split = item.get("split") or {}
    return {
        "period_year": split.get("periodYear"),
        "period_month": split.get("periodMonth"),
        "period_status": split.get("periodStatus"),
    }


def _period_attrs(item: JSON) -> dict[str, Any]:
    return {
        "year": item.get("year"),
        "month": item.get("month"),
        "is_current_month": item.get("isCurrentMonth"),
        "closed_at": item.get("closedAt"),
    }


def _status(item: JSON) -> str | None:
    status = item.get("status")
    return status if status in PERIOD_STATUSES else None


KID_SENSORS: tuple[HomeFinanceSensorEntityDescription, ...] = (
    _money("total", cents("totalCents"), balance=True),
    _money("ours", cents("pots", "ours", "balanceCents"), balance=True),
    _money("theirs", cents("pots", "theirs", "balanceCents"), balance=True),
    _money("net_this_month", cents("combined", "thisMonth", "netCents")),
    _money("net_this_year", cents("combined", "thisYear", "netCents")),
    _money("deposits_this_month", cents("combined", "thisMonth", "depositsCents")),
    _money("deposits_this_year", cents("combined", "thisYear", "depositsCents")),
    _money(
        "bank_balance",
        cents("bank", "reportedBalanceCents"),
        balance=True,
        attrs_fn=_bank_attrs,
    ),
    _money("bank_difference", cents("bank", "differenceCents"), attrs_fn=_bank_attrs),
    HomeFinanceSensorEntityDescription(
        key="last_entry",
        translation_key="last_entry",
        device_class=SensorDeviceClass.DATE,
        value_fn=day("lastEntry", "date"),
        attrs_fn=_kid_last_entry_attrs,
    ),
    _money("last_entry_amount", cents("lastEntry", "amountCents")),
    # Flow breakdowns: useful for checking the invariant, noisy on a dashboard.
    _money("opening_balance", cents("combined", "openingBalanceCents")),
    _money("deposits", cents("combined", "depositsCents")),
    _money("withdrawals", cents("combined", "withdrawalsCents")),
    _money("adjustments", cents("combined", "adjustmentsCents")),
    _money(
        "withdrawals_this_month",
        cents("combined", "thisMonth", "withdrawalsCents"),
    ),
    _money(
        "withdrawals_this_year",
        cents("combined", "thisYear", "withdrawalsCents"),
    ),
    _money(
        "ours_net_this_month",
        cents("pots", "ours", "thisMonth", "netCents"),
    ),
    _money("ours_net_this_year", cents("pots", "ours", "thisYear", "netCents")),
    _money(
        "theirs_net_this_month",
        cents("pots", "theirs", "thisMonth", "netCents"),
    ),
    _money(
        "theirs_net_this_year",
        cents("pots", "theirs", "thisYear", "netCents"),
    ),
)

POT_SENSORS: tuple[HomeFinanceSensorEntityDescription, ...] = (
    _money("balance", cents("balanceCents"), balance=True),
    _money("target", cents("target", "targetCents"), exists_fn=has_target),
    HomeFinanceSensorEntityDescription(
        key="progress",
        translation_key="progress",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value_fn=number("target", "progressPercent"),
        exists_fn=has_target,
    ),
    _money("remaining", cents("target", "remainingCents"), exists_fn=has_target),
    _money(
        "needed_per_month",
        cents("target", "neededPerMonthCents"),
        exists_fn=has_target_date,
    ),
    HomeFinanceSensorEntityDescription(
        key="months_left",
        translation_key="months_left",
        value_fn=number("target", "monthsLeft"),
        exists_fn=has_target_date,
    ),
    HomeFinanceSensorEntityDescription(
        key="target_date",
        translation_key="target_date",
        device_class=SensorDeviceClass.DATE,
        value_fn=day("target", "targetDate"),
        exists_fn=has_target_date,
    ),
    _money("allocated_this_month", cents("flows", "thisMonth", "allocationsCents")),
    _money("net_this_month", cents("flows", "thisMonth", "netCents")),
    _money("net_this_year", cents("flows", "thisYear", "netCents")),
    HomeFinanceSensorEntityDescription(
        key="split",
        translation_key="split",
        native_unit_of_measurement=PERCENTAGE,
        value_fn=number("split", "percentage"),
        attrs_fn=_split_attrs,
        exists_fn=has_split,
    ),
    HomeFinanceSensorEntityDescription(
        key="last_entry",
        translation_key="last_entry",
        device_class=SensorDeviceClass.DATE,
        value_fn=day("lastEntry", "date"),
        attrs_fn=_pot_last_entry_attrs,
    ),
    _money("opening_balance", cents("flows", "openingBalanceCents")),
    _money("allocations", cents("flows", "allocationsCents")),
    _money("deposits", cents("flows", "depositsCents")),
    _money("withdrawals", cents("flows", "withdrawalsCents")),
    _money("carryover_out", cents("flows", "carryoverOutCents")),
    _money("adjustments", cents("flows", "adjustmentsCents")),
    _money(
        "allocated_this_year",
        cents("flows", "thisYear", "allocationsCents"),
    ),
    _money("deposits_this_month", cents("flows", "thisMonth", "depositsCents")),
    _money(
        "withdrawals_this_month",
        cents("flows", "thisMonth", "withdrawalsCents"),
    ),
)

HOUSEHOLD_KID_SENSORS: tuple[HomeFinanceSensorEntityDescription, ...] = (
    _money("kids_total", cents("totalCents"), balance=True),
    _money("kids_ours", cents("oursCents"), balance=True),
    _money("kids_theirs", cents("theirsCents"), balance=True),
)

HOUSEHOLD_POT_SENSORS: tuple[HomeFinanceSensorEntityDescription, ...] = (
    _money("pots_total", cents("balanceCents"), balance=True),
    _money("pots_target_total", cents("targetCents")),
)

HOUSEHOLD_PERIOD_SENSORS: tuple[HomeFinanceSensorEntityDescription, ...] = (
    _money("month_income", cents("incomeCents"), attrs_fn=_period_attrs),
    _money("month_expenses", cents("expenseCents"), attrs_fn=_period_attrs),
    _money("month_surplus", cents("surplusCents"), attrs_fn=_period_attrs),
    HomeFinanceSensorEntityDescription(
        key="month_status",
        translation_key="month_status",
        device_class=SensorDeviceClass.ENUM,
        options=PERIOD_STATUSES,
        value_fn=_status,
        attrs_fn=_period_attrs,
    ),
)

HOUSEHOLD_YEAR_SENSORS: tuple[HomeFinanceSensorEntityDescription, ...] = (
    _money("year_income", cents("incomeCents")),
    _money("year_expenses", cents("expenseCents")),
    _money("year_surplus", cents("surplusCents")),
    _money("year_average_monthly_surplus", cents("averageMonthlySurplusCents")),
    HomeFinanceSensorEntityDescription(
        key="year_periods_open",
        translation_key="year_periods_open",
        value_fn=number("periodsOpen"),
    ),
    HomeFinanceSensorEntityDescription(
        key="year_periods_closed",
        translation_key="year_periods_closed",
        value_fn=number("periodsClosed"),
    ),
)

SENSORS: dict[tuple[Scope, str], tuple[HomeFinanceSensorEntityDescription, ...]] = {
    (scope, kind): with_default_enabled(kind, descs)
    for (scope, kind), descs in {
        (Scope.KIDS, KIND_HOUSEHOLD): HOUSEHOLD_KID_SENSORS,
        (Scope.KIDS, KIND_KID): KID_SENSORS,
        (Scope.POTS, KIND_HOUSEHOLD): HOUSEHOLD_POT_SENSORS,
        (Scope.POTS, KIND_POT): POT_SENSORS,
        (Scope.PERIODS, KIND_HOUSEHOLD): HOUSEHOLD_PERIOD_SENSORS,
        (Scope.YEARS, KIND_HOUSEHOLD): HOUSEHOLD_YEAR_SENSORS,
    }.items()
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: HomeFinanceConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up home-finance sensors."""
    async_setup_entities(
        hass,
        entry,
        async_add_entities,
        platform=Platform.SENSOR,
        entity_cls=HomeFinanceSensor,
        descriptions=SENSORS,
    )


class HomeFinanceSensor(HomeFinanceEntity, SensorEntity):
    """A home-finance sensor."""

    entity_description: HomeFinanceSensorEntityDescription

    @property
    def native_value(self) -> StateType | date | Decimal:
        """Return the value; ``None`` (unknown) for null fields."""
        item = self.item
        return None if item is None else self.entity_description.value_fn(item)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return the description's attributes."""
        item = self.item
        if item is None or self.entity_description.attrs_fn is None:
            return None
        return self.entity_description.attrs_fn(item)
