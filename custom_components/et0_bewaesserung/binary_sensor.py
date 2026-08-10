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
        ]
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
