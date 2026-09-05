"""Switch-Entität für die ET0-Bewässerungsintegration."""

from __future__ import annotations

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import Et0Coordinator


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator: Et0Coordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([SeasonActiveSwitch(coordinator, entry)])


class SeasonActiveSwitch(CoordinatorEntity[Et0Coordinator], SwitchEntity):
    """Schalter für die Bewässerungssaison - aus pausiert die komplette Logik."""

    _attr_name = "Gartensaison aktiv"
    _attr_icon = "mdi:sprinkler"

    def __init__(self, coordinator: Et0Coordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_season_active"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
            manufacturer="Lokale ET0-Integration",
        )

    @property
    def available(self) -> bool:
        """Immer bedienbar.

        Der Saison-Schalter ist ein rein lokaler Zustand und hängt nicht an
        den Wetter-Eingangsquellen. Gerade wenn eine Berechnung scheitert,
        soll man die Saison noch abschalten können.
        """
        return True

    @property
    def is_on(self) -> bool:
        if not self.coordinator.data:
            return True
        return bool(self.coordinator.data.get("season_active", True))

    async def async_turn_on(self, **kwargs) -> None:
        await self.coordinator.async_set_season_active(True)

    async def async_turn_off(self, **kwargs) -> None:
        await self.coordinator.async_set_season_active(False)
