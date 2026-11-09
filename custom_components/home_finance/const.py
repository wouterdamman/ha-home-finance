"""Constants for the home-finance integration."""

from __future__ import annotations

from datetime import timedelta
from enum import StrEnum
from typing import Final

DOMAIN: Final = "home_finance"
MANUFACTURER: Final = "home-finance"

CONF_SCOPES: Final = "scopes"
CONF_HOUSEHOLD_NAME: Final = "household_name"

# Suggested name of the Household device; it also seeds its entity IDs.
DEFAULT_HOUSEHOLD_NAME: Final = "Household"
HOUSEHOLD_NAME_BY_LANGUAGE: Final = {"nl": "Huishouden"}

DEFAULT_SCAN_INTERVAL: Final = timedelta(minutes=15)
MIN_SCAN_INTERVAL_MINUTES: Final = 5
MAX_SCAN_INTERVAL_MINUTES: Final = 1440

SUPPORTED_API_VERSION: Final = 1

# Entities enabled by default, per device kind. Every other entity still exists
# but starts disabled; enable it per entity in Home Assistant when needed.
DEFAULT_ENABLED: Final = {
    "kid": frozenset({"total", "ours", "theirs", "bank_difference", "last_entry"}),
    "pot": frozenset({"balance", "progress"}),
    "household": frozenset(
        {
            "kids_total",
            "pots_total",
            "month_income",
            "month_expenses",
            "month_surplus",
            "year_surplus",
        }
    ),
}

# Enabled by default up to v0.2.0 (config entry minor version 1). The migration
# to minor version 2 disables those that are no longer in DEFAULT_ENABLED.
ENABLED_BEFORE_MINOR_2: Final = {
    "kid": frozenset(
        {
            "total",
            "ours",
            "theirs",
            "net_this_month",
            "net_this_year",
            "deposits_this_month",
            "deposits_this_year",
            "bank_balance",
            "bank_difference",
            "last_entry",
            "last_entry_amount",
        }
    ),
    "pot": frozenset(
        {
            "balance",
            "target",
            "progress",
            "remaining",
            "needed_per_month",
            "months_left",
            "target_date",
            "allocated_this_month",
            "net_this_month",
            "net_this_year",
            "split",
            "last_entry",
            "goal_reached",
        }
    ),
    "household": frozenset(
        {
            "kids_total",
            "kids_ours",
            "kids_theirs",
            "pots_total",
            "pots_target_total",
            "month_income",
            "month_expenses",
            "month_surplus",
            "month_status",
            "year_income",
            "year_expenses",
            "year_surplus",
            "year_average_monthly_surplus",
        }
    ),
}


class Scope(StrEnum):
    """Token scopes the integration understands."""

    KIDS = "kids:read"
    POTS = "pots:read"
    PERIODS = "periods:read"
    YEARS = "years:read"


SCOPES: Final = tuple(Scope)
