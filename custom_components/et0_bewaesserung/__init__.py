"""Lokale Integration: ET0-basierte Bewässerungssteuerung."""

from __future__ import annotations

import unicodedata

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv

from .const import DOMAIN
from .coordinator import Et0Coordinator

PLATFORMS = [Platform.SENSOR, Platform.SWITCH, Platform.BINARY_SENSOR]

RESET_DEFICIT_SCHEMA = vol.Schema(
    {
        vol.Optional("zone"): cv.string,
        vol.Optional("amount_mm"): vol.Coerce(float),
    }
)

EQUIPMENT_STATUS_SCHEMA = vol.Schema({vol.Required("verstaut"): cv.boolean})


def _normalize(text: str) -> str:
    """Unicode-normalisiert (NFC) einen Namen für sicheren Vergleich.

    Umlaute wie "ä" können auf zwei binär unterschiedliche Arten kodiert
    sein (vorkomponiert vs. Basiszeichen + Kombinationszeichen) - beide
    sehen identisch aus, sind aber mit "==" nicht gleich. Je nachdem, ob
    ein Name über die UI, ein YAML-Editor oder ein anderes Gerät
    eingegeben wurde, kann das variieren. Normalisierung vor dem
    Vergleich macht den Zonen-Namensabgleich robust dagegen.
    """
    return unicodedata.normalize("NFC", text).strip()


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    coordinator = Et0Coordinator(hass, entry)
    await coordinator.async_setup()
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))

    async def handle_recalculate(call: ServiceCall) -> None:
        await coordinator.async_refresh()
        if not coordinator.last_update_success:
            raise HomeAssistantError(
                f"ET0-Neuberechnung fehlgeschlagen: {coordinator.last_exception}"
            )

    async def handle_reset_deficit(call: ServiceCall) -> None:
        zone_name = call.data.get("zone")
        amount_mm = call.data.get("amount_mm")
        zone_index = None
        if zone_name:
            zone_name_norm = _normalize(zone_name)
            for zone in coordinator.get_zone_definitions():
                if _normalize(zone["name"]) == zone_name_norm:
                    zone_index = zone["index"]
                    break
            else:
                raise HomeAssistantError(f"Zone '{zone_name}' nicht gefunden")
        await coordinator.async_reset_deficit(zone_index, amount_mm=amount_mm)

    hass.services.async_register(DOMAIN, "recalculate", handle_recalculate)
    hass.services.async_register(
        DOMAIN, "reset_deficit", handle_reset_deficit, schema=RESET_DEFICIT_SCHEMA
    )

    async def handle_equipment_status(call: ServiceCall) -> None:
        await coordinator.async_set_equipment_stored(call.data["verstaut"])

    hass.services.async_register(
        DOMAIN,
        "equipment_status_setzen",
        handle_equipment_status,
        schema=EQUIPMENT_STATUS_SCHEMA,
    )

    return True


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    coordinator: Et0Coordinator = hass.data[DOMAIN][entry.entry_id]
    coordinator.async_unload()
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        hass.data[DOMAIN].pop(entry.entry_id)
    return unloaded
