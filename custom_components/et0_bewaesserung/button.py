"""Button-Plattform für ET0 Bewässerung."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import Et0Coordinator


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator: Et0Coordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([RecalculateButton(coordinator, entry)])


class RecalculateButton(CoordinatorEntity[Et0Coordinator], ButtonEntity):
    """Stößt eine sofortige Neuberechnung an.

    War bisher nur als Aktion in den Entwicklerwerkzeugen erreichbar. Seit dem
    Umbau auf das idempotente carry/today-Modell (v1.4.0) ist ein manueller
    Aufruf zu jeder Tages- und Nachtzeit unschädlich - deshalb jetzt auch als
    normale Dashboard-Kachel verfügbar, nicht mehr "versteckt".
    """

    _attr_name = "Jetzt neu berechnen"
    _attr_icon = "mdi:calculator-variant-outline"

    def __init__(self, coordinator: Et0Coordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_recalculate_button"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
            manufacturer="Lokale ET0-Integration",
        )

    async def async_press(self) -> None:
        await self.coordinator.async_refresh()
        if not self.coordinator.last_update_success:
            raise HomeAssistantError(
                f"ET0-Neuberechnung fehlgeschlagen: "
                f"{self.coordinator.last_exception}"
            )
