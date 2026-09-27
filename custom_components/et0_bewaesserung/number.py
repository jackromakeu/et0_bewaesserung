"""Number-Entitäten für die ET0-Bewässerungsintegration.

Hier liegen die beiden Betriebswerte je Zone, die man im Lauf einer Saison
tatsächlich nachzieht: das Mindestdefizit, ab dem überhaupt gegossen wird,
und der Mindestabstand zwischen zwei Läufen.

Warum als Entity und nicht im Config Flow (wo sie bis v2.1.3 standen):

1. Anzeige. Ohne den Schwellenwert als Entity kann ein Dashboard nur
   "Mindestdefizit erfüllt: nein" zeigen. Mit ihm wird daraus "2,1 von
   3,0 mm" - der Unterschied zwischen einem Statuslämpchen und einer Aussage.
   Auch eine Gauge-Skala bekommt damit erst einen Bezugspunkt.
2. Justierung. Eine Schwelle im Config Flow nachzuziehen heißt: Optionen
   öffnen, speichern, Reload - mitten in der Saison ein Eingriff mit
   Reload-Risiko für den Koordinatorzustand.
3. Sichtbarkeit. Das ist der eigentliche Punkt. Eine im Config Flow
   verstellte Schwelle ist eine stille Änderung: Recorder und Logbuch sehen
   sie nicht, und drei Wochen später ist nicht mehr nachvollziehbar, warum
   der Rasen seltener läuft. Als Entity ist jede Änderung aufgezeichnet.

Der Zustand gehört dem Coordinator und wird in dessen Store gehalten, nicht
in der Entity: Der erste Berechnungslauf passiert in async_setup_entry, also
BEVOR die Plattformen geladen sind - eine RestoreNumber wäre zu diesem
Zeitpunkt noch nicht da. Dasselbe Muster wie beim Saison-Schalter.
"""

from __future__ import annotations

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    DOMAIN,
    CONF_ZONE_MIN_DAYS,
    CONF_ZONE_MIN_DEFICIT_MM,
)
from .coordinator import Et0Coordinator


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator: Et0Coordinator = hass.data[DOMAIN][entry.entry_id]

    for zone in coordinator.get_zone_definitions():
        zid = zone["id"]
        name = zone["name"]
        async_add_entities(
            [
                ZoneMinDeficitNumber(coordinator, entry, zid, name),
                ZoneMinDaysNumber(coordinator, entry, zid, name),
            ],
            config_subentry_id=zid,
        )


class ZoneRuntimeNumber(CoordinatorEntity[Et0Coordinator], NumberEntity):
    """Basis für die verstellbaren Betriebswerte einer Zone."""

    # CONFIG statt keiner Kategorie: der Wert steuert die Anlage, er ist
    # keine Messung. HA sortiert die Entity damit auf der Geräteseite unter
    # "Konfiguration" ein und hält sie aus Sprachassistenten heraus - im
    # Recorder landet sie trotzdem, was hier der ganze Zweck ist.
    _attr_entity_category = EntityCategory.CONFIG
    _runtime_key: str = ""

    def __init__(
        self,
        coordinator: Et0Coordinator,
        entry: ConfigEntry,
        zone_id: str,
        zone_name: str,
    ) -> None:
        super().__init__(coordinator)
        self._zone_id = zone_id
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{entry.entry_id}_{zone_id}")},
            name=f"Zone {zone_name}",
            manufacturer="Lokale ET0-Integration",
            via_device_id=coordinator.main_device_id,
        )

    @property
    def available(self) -> bool:
        """Immer bedienbar.

        Die Schwellen sind rein lokale Policy und hängen nicht an den
        Wetter-Eingangsquellen. Gerade wenn eine Berechnung scheitert, muss
        man sie noch verstellen können - gleiche Begründung wie beim
        Saison-Schalter und beim Neuberechnen-Button.
        """
        return True

    @property
    def native_value(self) -> float | None:
        return self.coordinator.get_zone_runtime(self._zone_id, self._runtime_key)

    async def async_set_native_value(self, value: float) -> None:
        await self.coordinator.async_set_zone_runtime(
            self._zone_id, self._runtime_key, value
        )


class ZoneMinDeficitNumber(ZoneRuntimeNumber):
    """Mindestdefizit in mm, ab dem eine Zone überhaupt gegossen wird."""

    _runtime_key = CONF_ZONE_MIN_DEFICIT_MM
    _attr_icon = "mdi:water-check"
    _attr_native_unit_of_measurement = "mm"
    _attr_native_min_value = 0.0
    _attr_native_max_value = 20.0
    _attr_native_step = 0.5
    _attr_mode = NumberMode.SLIDER

    def __init__(self, coordinator, entry, zone_id, zone_name):
        super().__init__(coordinator, entry, zone_id, zone_name)
        self._attr_unique_id = f"{entry.entry_id}_{zone_id}_min_deficit_setpoint"
        self._attr_name = f"Mindestdefizit {zone_name}"


class ZoneMinDaysNumber(ZoneRuntimeNumber):
    """Mindestabstand in Tagen zwischen zwei Bewässerungen derselben Zone."""

    _runtime_key = CONF_ZONE_MIN_DAYS
    _attr_icon = "mdi:calendar-range"
    _attr_native_unit_of_measurement = UnitOfTime.DAYS
    _attr_native_min_value = 1
    _attr_native_max_value = 14
    _attr_native_step = 1
    _attr_mode = NumberMode.SLIDER

    def __init__(self, coordinator, entry, zone_id, zone_name):
        super().__init__(coordinator, entry, zone_id, zone_name)
        self._attr_unique_id = f"{entry.entry_id}_{zone_id}_min_days_setpoint"
        self._attr_name = f"Mindestabstand {zone_name}"
