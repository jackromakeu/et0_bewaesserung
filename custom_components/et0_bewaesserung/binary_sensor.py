"""Binary-Sensor-Entitäten für die ET0-Bewässerungsintegration."""

from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorEntity
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
    async_add_entities(
        [
            FrostWarningSensor(coordinator, entry),
            SpringReadySensor(coordinator, entry),
            EquipmentStoredSensor(coordinator, entry),
            RainExpectedSensor(coordinator, entry),
        ]
    )

    for zone in coordinator.get_zone_definitions():
        zid = zone["id"]
        name = zone["name"]
        async_add_entities(
            [
                ZoneMinIntervalSensor(coordinator, entry, zid, name),
                ZoneMinDeficitSensor(coordinator, entry, zid, name),
            ],
            config_subentry_id=zid,
        )


class Et0BinaryBaseEntity(CoordinatorEntity[Et0Coordinator], BinarySensorEntity):
    def __init__(self, coordinator: Et0Coordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
            manufacturer="Lokale ET0-Integration",
        )

    @property
    def available(self) -> bool:
        """Verfügbar, solange Daten vorliegen - siehe Et0BaseEntity in sensor.py."""
        return self.coordinator.data is not None


class FrostWarningSensor(Et0BinaryBaseEntity):
    """Aktiv, sobald Frost erwartet wird und das Equipment noch nicht verstaut ist.

    Bleibt aktiv ("sticky"), bis das Equipment über den Service
    equipment_status_setzen als verstaut bestätigt wird - unabhängig davon,
    ob die Vorhersage zwischenzeitlich wieder milder wird.
    """

    _attr_name = "Frost erwartet - Equipment-Abbau nötig"
    _attr_icon = "mdi:snowflake-alert"
    _attr_device_class = "cold"

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_frost_warning"

    @property
    def is_on(self):
        if not self.coordinator.data:
            return False
        return bool(self.coordinator.data.get("frost_warning_active", False))


class SpringReadySensor(Et0BinaryBaseEntity):
    """Aktiv, sobald Frühjahrsbedingungen für den Equipment-Wiederaufbau erfüllt sind.

    Bleibt aktiv ("sticky"), bis das Equipment über den Service
    equipment_status_setzen als wieder aufgebaut bestätigt wird.
    """

    _attr_name = "Frühjahr bereit - Equipment-Aufbau möglich"
    _attr_icon = "mdi:flower"

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_spring_ready"

    @property
    def is_on(self):
        if not self.coordinator.data:
            return False
        return bool(self.coordinator.data.get("spring_ready_active", False))


class EquipmentStoredSensor(Et0BinaryBaseEntity):
    """Aktueller Equipment-Status: an = verstaut (Winter), aus = aufgebaut (Sommer)."""

    _attr_name = "Equipment verstaut"
    _attr_icon = "mdi:garage"

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_equipment_stored"

    @property
    def is_on(self):
        if not self.coordinator.data:
            return False
        return bool(self.coordinator.data.get("equipment_stored", False))


class RainExpectedSensor(Et0BinaryBaseEntity):
    """Globaler Regen-Skip-Status: an = für HEUTE wird Regen über der
    konfigurierten Schwelle erwartet, alle Zonen setzen die Bewässerung aus.

    Der Wert wird beim Mitternachts-Rollover fixiert und bleibt für den
    ganzen Tag stabil - unabhängig davon, ob eine Zone morgens oder abends
    gießt (siehe coordinator._rollover_if_needed). Der Name der Entity blieb
    aus Kompatibilitätsgründen unverändert (Entity-ID ändert sich dadurch
    nicht), nur die Bedeutung wurde von "morgen" auf "heute" präzisiert.
    """

    _attr_name = "Regen erwartet (Skip aktiv heute)"
    _attr_icon = "mdi:weather-pouring"
    _attr_device_class = "moisture"

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_rain_expected"

    @property
    def is_on(self):
        if not self.coordinator.data:
            return False
        return bool(self.coordinator.data.get("rain_expected", False))

    @property
    def extra_state_attributes(self):
        if not self.coordinator.data:
            return {}
        d = self.coordinator.data
        return {
            "regen_prognose_heute_mm": d.get("forecast_precip_today_mm"),
            "regen_prognose_morgen_mm": d.get("forecast_precip_tomorrow_mm"),
            "skip_aktiv_morgen": d.get("rain_skip_tomorrow"),
        }


class ZoneBinaryBaseEntity(Et0BinaryBaseEntity):
    """Basis für alle Zonen-spezifischen Binary-Sensoren."""

    def __init__(self, coordinator, entry, zone_id: str, zone_name: str):
        super().__init__(coordinator, entry)
        self._zone_id = zone_id
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{entry.entry_id}_{zone_id}")},
            name=f"Zone {zone_name}",
            manufacturer="Lokale ET0-Integration",
            via_device=(DOMAIN, entry.entry_id),
        )

    def _zone_data(self) -> dict | None:
        if not self.coordinator.data:
            return None
        return self.coordinator.data.get("zones", {}).get(self._zone_id)


class ZoneMinIntervalSensor(ZoneBinaryBaseEntity):
    """An = Mindestabstand seit letzter Bewässerung dieser Zone ist erfüllt."""

    _attr_icon = "mdi:calendar-check"

    def __init__(self, coordinator, entry, zone_id, zone_name):
        super().__init__(coordinator, entry, zone_id, zone_name)
        self._attr_unique_id = f"{entry.entry_id}_{zone_id}_min_interval"
        self._attr_name = f"Mindestabstand erfüllt {zone_name}"

    @property
    def is_on(self):
        zone = self._zone_data()
        return bool(zone.get("min_interval_ok", True)) if zone else True

    @property
    def extra_state_attributes(self):
        zone = self._zone_data()
        if not zone:
            return {}
        return {"tage_seit_letzter_bewaesserung": zone.get("days_since_watered")}


class ZoneMinDeficitSensor(ZoneBinaryBaseEntity):
    """An = das konfigurierte Mindestdefizit dieser Zone ist erreicht."""

    _attr_icon = "mdi:water-check"

    def __init__(self, coordinator, entry, zone_id, zone_name):
        super().__init__(coordinator, entry, zone_id, zone_name)
        self._attr_unique_id = f"{entry.entry_id}_{zone_id}_min_deficit"
        self._attr_name = f"Mindestdefizit erfüllt {zone_name}"

    @property
    def is_on(self):
        zone = self._zone_data()
        return bool(zone.get("min_deficit_ok", True)) if zone else True
