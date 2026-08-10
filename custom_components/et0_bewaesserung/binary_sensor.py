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
    entities: list[Et0BinaryBaseEntity] = [
        FrostWarningSensor(coordinator, entry),
        SpringReadySensor(coordinator, entry),
        EquipmentStoredSensor(coordinator, entry),
        RainExpectedSensor(coordinator, entry),
    ]

    for zone in coordinator.get_zone_definitions():
        idx = zone["index"]
        name = zone["name"]
        entities.append(ZoneMinIntervalSensor(coordinator, entry, idx, name))
        entities.append(ZoneMinDeficitSensor(coordinator, entry, idx, name))

    async_add_entities(entities)


class Et0BinaryBaseEntity(CoordinatorEntity[Et0Coordinator], BinarySensorEntity):
    def __init__(self, coordinator: Et0Coordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
            manufacturer="Lokale ET0-Integration",
        )


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
    """Globaler Regen-Skip-Status: an = für morgen wird Regen über der
    konfigurierten Schwelle erwartet, alle Zonen setzen die Bewässerung aus."""

    _attr_name = "Regen erwartet (Skip aktiv)"
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
        return {
            "regen_prognose_morgen_mm": self.coordinator.data.get("forecast_precip_mm")
        }


class ZoneBinaryBaseEntity(Et0BinaryBaseEntity):
    """Basis für alle Zonen-spezifischen Binary-Sensoren."""

    def __init__(self, coordinator, entry, zone_index: int, zone_name: str):
        super().__init__(coordinator, entry)
        self._zone_index = zone_index

    def _zone_data(self) -> dict | None:
        if not self.coordinator.data:
            return None
        return self.coordinator.data.get("zones", {}).get(self._zone_index)


class ZoneMinIntervalSensor(ZoneBinaryBaseEntity):
    """An = Mindestabstand seit letzter Bewässerung dieser Zone ist erfüllt."""

    _attr_icon = "mdi:calendar-check"

    def __init__(self, coordinator, entry, zone_index, zone_name):
        super().__init__(coordinator, entry, zone_index, zone_name)
        self._attr_unique_id = f"{entry.entry_id}_zone{zone_index}_min_interval"
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

    def __init__(self, coordinator, entry, zone_index, zone_name):
        super().__init__(coordinator, entry, zone_index, zone_name)
        self._attr_unique_id = f"{entry.entry_id}_zone{zone_index}_min_deficit"
        self._attr_name = f"Mindestdefizit erfüllt {zone_name}"

    @property
    def is_on(self):
        zone = self._zone_data()
        return bool(zone.get("min_deficit_ok", True)) if zone else True
