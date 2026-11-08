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


class Scope(StrEnum):
    """Token scopes the integration understands."""

    KIDS = "kids:read"
    POTS = "pots:read"
    PERIODS = "periods:read"
    YEARS = "years:read"


SCOPES: Final = tuple(Scope)
