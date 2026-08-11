"""Sensor-Entitäten für die ET0-Bewässerungsintegration."""

from __future__ import annotations

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .const import DOMAIN
from .coordinator import Et0Coordinator


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator: Et0Coordinator = hass.data[DOMAIN][entry.entry_id]

    entities: list[Et0BaseEntity] = [
        Et0Sensor(coordinator, entry),
        RsProxySensor(coordinator, entry),
        DeficitSensor(coordinator, entry),
    ]

    for zone in coordinator.get_zone_definitions():
        idx = zone["index"]
        name = zone["name"]
        entities.append(ZoneEtcSensor(coordinator, entry, idx, name))
        entities.append(ZoneDeficitSensor(coordinator, entry, idx, name))
        entities.append(ZoneDurationSensor(coordinator, entry, idx, name))
        entities.append(ZoneLastWateredSensor(coordinator, entry, idx, name))
        entities.append(ZoneRunningDeficitSensor(coordinator, entry, idx, name))

    async_add_entities(entities)


class Et0BaseEntity(CoordinatorEntity[Et0Coordinator], SensorEntity):
    def __init__(self, coordinator: Et0Coordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
            manufacturer="Lokale ET0-Integration",
        )


class Et0Sensor(Et0BaseEntity):
    _attr_name = "ET0 Tagesreferenz"
    _attr_native_unit_of_measurement = "mm"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:water-percent"

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_et0"

    @property
    def native_value(self):
        return self.coordinator.data.get("et0") if self.coordinator.data else None

    @property
    def extra_state_attributes(self):
        if not self.coordinator.data:
            return {}
        d = self.coordinator.data
        return {
            "rs_mj_m2": d.get("rs"),
            "rn_mj_m2": d.get("rn"),
            "tmean": d.get("tmean"),
            "u2_m_s": d.get("u2"),
            "regen_erwartet_morgen": d.get("rain_expected"),
            "regen_prognose_morgen_mm": d.get("forecast_precip_mm"),
            "fallback_werte_verwendet": d.get("fallback_used") or "keine",
            "laufender_tag": d.get("current_day"),
            "heutiger_beitrag_referenz_mm": d.get("today_contribution_global"),
            "defizit_laufend_mm": d.get("deficit_running"),
        }


class RsProxySensor(Et0BaseEntity):
    _attr_name = "Solarstrahlung (PV-Proxy)"
    _attr_native_unit_of_measurement = "MJ/m²"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:solar-power"

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_rs"

    @property
    def native_value(self):
        return self.coordinator.data.get("rs") if self.coordinator.data else None


class DeficitSensor(Et0BaseEntity):
    _attr_name = "Bewässerungsdefizit"
    _attr_native_unit_of_measurement = "mm"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:water-alert"

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_deficit"

    @property
    def native_value(self):
        return self.coordinator.data.get("deficit") if self.coordinator.data else None

    @property
    def extra_state_attributes(self):
        if not self.coordinator.data:
            return {}
        return {"niederschlag_mm": self.coordinator.data.get("precipitation")}


class ZoneBaseEntity(Et0BaseEntity):
    """Basis für alle Zonen-Sensoren."""

    def __init__(self, coordinator, entry, zone_index: int, zone_name: str):
        super().__init__(coordinator, entry)
        self._zone_index = zone_index

    def _zone_data(self) -> dict | None:
        if not self.coordinator.data:
            return None
        return self.coordinator.data.get("zones", {}).get(self._zone_index)


class ZoneEtcSensor(ZoneBaseEntity):
    _attr_native_unit_of_measurement = "mm"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:water"

    def __init__(self, coordinator, entry, zone_index, zone_name):
        super().__init__(coordinator, entry, zone_index, zone_name)
        self._attr_unique_id = f"{entry.entry_id}_zone{zone_index}_etc"
        self._attr_name = f"ETc {zone_name}"

    @property
    def native_value(self):
        zone = self._zone_data()
        return zone["etc"] if zone else None


class ZoneDeficitSensor(ZoneBaseEntity):
    _attr_native_unit_of_measurement = "mm"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:water-alert"

    def __init__(self, coordinator, entry, zone_index, zone_name):
        super().__init__(coordinator, entry, zone_index, zone_name)
        self._attr_unique_id = f"{entry.entry_id}_zone{zone_index}_deficit"
        self._attr_name = f"Bewässerungsdefizit {zone_name}"

    @property
    def native_value(self):
        zone = self._zone_data()
        return zone["deficit"] if zone else None

    @property
    def extra_state_attributes(self):
        zone = self._zone_data()
        if not zone or not self.coordinator.data:
            return {}
        return {
            "heutiger_beitrag_mm": zone.get("today_contribution_mm"),
            "defizit_laufend_mm": zone.get("deficit_running"),
            "laufender_tag": self.coordinator.data.get("current_day"),
        }


class ZoneDurationSensor(ZoneBaseEntity):
    _attr_native_unit_of_measurement = UnitOfTime.MINUTES
    _attr_device_class = SensorDeviceClass.DURATION
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:timer-water-outline"

    def __init__(self, coordinator, entry, zone_index, zone_name):
        super().__init__(coordinator, entry, zone_index, zone_name)
        self._attr_unique_id = f"{entry.entry_id}_zone{zone_index}_duration"
        self._attr_name = f"Bewässerungsdauer {zone_name}"

    @property
    def native_value(self):
        zone = self._zone_data()
        return zone["duration_min"] if zone else None

    @property
    def extra_state_attributes(self):
        zone = self._zone_data()
        if not zone:
            return {}
        return {
            "regen_skip_aktiv": zone.get("rain_skip", False),
            "mindestabstand_erfuellt": zone.get("min_interval_ok", True),
            "tage_seit_letzter_bewaesserung": zone.get("days_since_watered"),
            "mindestdefizit_erfuellt": zone.get("min_deficit_ok", True),
            "bewaesserung_erlaubt": zone.get("watering_allowed", False),
        }


class ZoneLastWateredSensor(ZoneBaseEntity):
    """Zeitpunkt der letzten tatsächlichen Bewässerung dieser Zone.

    Wird gesetzt, wenn eine Automation nach dem Gießen den Service
    et0_bewaesserung.reset_deficit für diese Zone aufruft (optional mit
    der abgegebenen Menge in mm).
    """

    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_icon = "mdi:history"

    def __init__(self, coordinator, entry, zone_index, zone_name):
        super().__init__(coordinator, entry, zone_index, zone_name)
        self._attr_unique_id = f"{entry.entry_id}_zone{zone_index}_last_watered"
        self._attr_name = f"Zuletzt bewässert {zone_name}"

    @property
    def native_value(self):
        zone = self._zone_data()
        if not zone or not zone.get("last_watered_timestamp"):
            return None
        return dt_util.parse_datetime(zone["last_watered_timestamp"])

    @property
    def extra_state_attributes(self):
        zone = self._zone_data()
        if not zone:
            return {}
        amount = zone.get("last_watered_amount_mm")
        return {"menge_mm": amount if amount is not None else "unbekannt"}


class ZoneRunningDeficitSensor(ZoneBaseEntity):
    """Laufendes Defizit dieser Zone: abgeschlossene Tage + laufender Tag.

    Im Gegensatz zu "Bewässerungsdefizit <Zone>" (= Basis für die
    Gieß-Entscheidung, ändert sich nur beim Tageswechsel und beim Gießen)
    enthält dieser Wert zusätzlich den bereits berechneten Beitrag des
    LAUFENDEN Tages. Nützlich fürs Dashboard, weil er sich im Tagesverlauf
    tatsächlich bewegt, statt nach dem morgendlichen Gießen bis zum Abend
    auf 0 stehen zu bleiben.
    """

    _attr_native_unit_of_measurement = "mm"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:water-sync"

    def __init__(self, coordinator, entry, zone_index, zone_name):
        super().__init__(coordinator, entry, zone_index, zone_name)
        self._attr_unique_id = f"{entry.entry_id}_zone{zone_index}_deficit_running"
        self._attr_name = f"Defizit laufend {zone_name}"

    @property
    def native_value(self):
        zone = self._zone_data()
        return zone.get("deficit_running") if zone else None
