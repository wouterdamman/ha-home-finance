"""Binary sensors for savings pots."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.binary_sensor import BinarySensorEntity, BinarySensorEntityDescription
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import HomeFinanceConfigEntry
from .api import JSON
from .const import Scope
from .entity import KIND_POT, HomeFinanceEntity, async_setup_entities, dig, has_target

PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class HomeFinanceBinarySensorEntityDescription(BinarySensorEntityDescription):
    """A binary sensor description that knows how to read its value."""

    value_fn: Callable[[JSON], bool | None]
    exists_fn: Callable[[JSON], bool] | None = None


def _reached(item: JSON) -> bool | None:
    reached = dig(item, "target", "reached")
    return reached if isinstance(reached, bool) else None


POT_BINARY_SENSORS: tuple[HomeFinanceBinarySensorEntityDescription, ...] = (
    HomeFinanceBinarySensorEntityDescription(
        key="goal_reached",
        translation_key="goal_reached",
        value_fn=_reached,
        exists_fn=has_target,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: HomeFinanceConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up home-finance binary sensors."""
    async_setup_entities(
        hass,
        entry,
        async_add_entities,
        platform=Platform.BINARY_SENSOR,
        entity_cls=HomeFinanceBinarySensor,
        descriptions={(Scope.POTS, KIND_POT): POT_BINARY_SENSORS},
    )


class HomeFinanceBinarySensor(HomeFinanceEntity, BinarySensorEntity):
    """A home-finance binary sensor."""

    entity_description: HomeFinanceBinarySensorEntityDescription

    @property
    def is_on(self) -> bool | None:
        """Return the state; ``None`` (unknown) for a pot without a target."""
        item = self.item
        return None if item is None else self.entity_description.value_fn(item)
