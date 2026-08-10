"""Config Flow für die ET0-Bewässerungsintegration."""

from __future__ import annotations

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import selector

from .const import (
    DOMAIN,
    CONF_TEMP_MAX_ENTITY,
    CONF_TEMP_MIN_ENTITY,
    CONF_HUMIDITY_MEAN_ENTITY,
    CONF_WIND_MEAN_ENTITY,
    CONF_PV_YIELD_ENTITY,
    CONF_WEATHER_ENTITY,
    CONF_LATITUDE,
    CONF_ELEVATION,
    CONF_KWP,
    CONF_PERFORMANCE_RATIO,
    CONF_UPDATE_TIME,
    DEFAULT_UPDATE_TIME,
    DEFAULT_PERFORMANCE_RATIO,
    MAX_ZONES,
    DEFAULT_ZONE_NAMES,
    DEFAULT_ZONE_KC,
    DEFAULT_ZONE_DRIP_RATE,
    zone_key,
    CONF_RAIN_SKIP_ENABLED,
    CONF_RAIN_SKIP_THRESHOLD,
    DEFAULT_RAIN_SKIP_ENABLED,
    DEFAULT_RAIN_SKIP_THRESHOLD,
    CONF_FROST_LOOKAHEAD_DAYS,
    DEFAULT_FROST_LOOKAHEAD_DAYS,
    CONF_FROST_THRESHOLD,
    DEFAULT_FROST_THRESHOLD,
    CONF_SPRING_EARLIEST_DATE,
    DEFAULT_SPRING_EARLIEST_DATE,
)

REQUIRED_ENTITY_FIELDS = (
    CONF_TEMP_MAX_ENTITY,
    CONF_TEMP_MIN_ENTITY,
    CONF_HUMIDITY_MEAN_ENTITY,
    CONF_WIND_MEAN_ENTITY,
    CONF_PV_YIELD_ENTITY,
)


def _build_general_schema(hass: HomeAssistant, defaults: dict) -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(
                CONF_TEMP_MAX_ENTITY, default=defaults.get(CONF_TEMP_MAX_ENTITY)
            ): selector.EntitySelector(selector.EntitySelectorConfig(domain="sensor")),
            vol.Required(
                CONF_TEMP_MIN_ENTITY, default=defaults.get(CONF_TEMP_MIN_ENTITY)
            ): selector.EntitySelector(selector.EntitySelectorConfig(domain="sensor")),
            vol.Required(
                CONF_HUMIDITY_MEAN_ENTITY,
                default=defaults.get(CONF_HUMIDITY_MEAN_ENTITY),
            ): selector.EntitySelector(selector.EntitySelectorConfig(domain="sensor")),
            vol.Required(
                CONF_WIND_MEAN_ENTITY, default=defaults.get(CONF_WIND_MEAN_ENTITY)
            ): selector.EntitySelector(selector.EntitySelectorConfig(domain="sensor")),
            vol.Required(
                CONF_PV_YIELD_ENTITY, default=defaults.get(CONF_PV_YIELD_ENTITY)
            ): selector.EntitySelector(selector.EntitySelectorConfig(domain="sensor")),
            vol.Optional(
                CONF_WEATHER_ENTITY, default=defaults.get(CONF_WEATHER_ENTITY, "")
            ): selector.EntitySelector(selector.EntitySelectorConfig(domain="weather")),
            vol.Required(
                CONF_LATITUDE,
                default=defaults.get(CONF_LATITUDE, hass.config.latitude),
            ): selector.NumberSelector(
                # step >= 0.001 ist Pflicht (siehe NumberSelector-Validierung in HA) -
                # ein kleinerer Wert führt zu einem stillen 400-Fehler ohne Log!
                selector.NumberSelectorConfig(min=-90, max=90, step=0.001, mode="box")
            ),
            vol.Required(
                CONF_ELEVATION,
                default=defaults.get(CONF_ELEVATION, hass.config.elevation),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(min=0, max=3000, step=1, mode="box")
            ),
            vol.Required(
                CONF_KWP, default=defaults.get(CONF_KWP, 5.1)
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(min=0.1, max=100, step=0.1, mode="box")
            ),
            vol.Required(
                CONF_PERFORMANCE_RATIO,
                default=defaults.get(CONF_PERFORMANCE_RATIO, DEFAULT_PERFORMANCE_RATIO),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(min=0.5, max=1.0, step=0.01, mode="box")
            ),
            vol.Required(
                CONF_UPDATE_TIME,
                default=defaults.get(CONF_UPDATE_TIME, DEFAULT_UPDATE_TIME),
            ): str,
            vol.Required(
                CONF_RAIN_SKIP_ENABLED,
                default=defaults.get(CONF_RAIN_SKIP_ENABLED, DEFAULT_RAIN_SKIP_ENABLED),
            ): selector.BooleanSelector(),
            vol.Required(
                CONF_RAIN_SKIP_THRESHOLD,
                default=defaults.get(
                    CONF_RAIN_SKIP_THRESHOLD, DEFAULT_RAIN_SKIP_THRESHOLD
                ),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(min=0, max=50, step=0.5, mode="box")
            ),
            vol.Required(
                CONF_FROST_LOOKAHEAD_DAYS,
                default=defaults.get(
                    CONF_FROST_LOOKAHEAD_DAYS, DEFAULT_FROST_LOOKAHEAD_DAYS
                ),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(min=1, max=10, step=1, mode="box")
            ),
            vol.Required(
                CONF_FROST_THRESHOLD,
                default=defaults.get(CONF_FROST_THRESHOLD, DEFAULT_FROST_THRESHOLD),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(min=-5, max=5, step=0.5, mode="box")
            ),
            vol.Required(
                CONF_SPRING_EARLIEST_DATE,
                default=defaults.get(
                    CONF_SPRING_EARLIEST_DATE, DEFAULT_SPRING_EARLIEST_DATE
                ),
            ): str,
        }
    )


def _build_zone_schema(defaults: dict) -> vol.Schema:
    schema_dict: dict = {}
    for i in range(MAX_ZONES):
        schema_dict[
            vol.Optional(
                zone_key(i, "name"),
                default=defaults.get(zone_key(i, "name"), DEFAULT_ZONE_NAMES[i]),
            )
        ] = str
        schema_dict[
            vol.Optional(
                zone_key(i, "kc"),
                default=defaults.get(zone_key(i, "kc"), DEFAULT_ZONE_KC[i]),
            )
        ] = selector.NumberSelector(
            selector.NumberSelectorConfig(min=0.1, max=1.5, step=0.05, mode="box")
        )
        schema_dict[
            vol.Optional(
                zone_key(i, "drip_rate"),
                default=defaults.get(zone_key(i, "drip_rate"), DEFAULT_ZONE_DRIP_RATE[i]),
            )
        ] = selector.NumberSelector(
            selector.NumberSelectorConfig(min=0.01, max=5.0, step=0.01, mode="box")
        )
    return vol.Schema(schema_dict)


async def _validate_entities(hass: HomeAssistant, user_input: dict) -> dict[str, str]:
    """Prüft die gewählten Entities auf Existenz und einen gültigen Zahlenwert."""
    errors: dict[str, str] = {}

    for key in REQUIRED_ENTITY_FIELDS:
        entity_id = user_input.get(key)
        if not entity_id:
            errors[key] = "entity_not_found"
            continue
        state = hass.states.get(entity_id)
        if state is None:
            errors[key] = "entity_not_found"
        elif state.state in ("unknown", "unavailable", "", None):
            errors[key] = "entity_no_value"
        else:
            try:
                float(state.state)
            except (ValueError, TypeError):
                errors[key] = "entity_not_numeric"

    weather_entity = user_input.get(CONF_WEATHER_ENTITY)
    if weather_entity and hass.states.get(weather_entity) is None:
        errors[CONF_WEATHER_ENTITY] = "entity_not_found"

    return errors


class Et0ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Ersteinrichtung über die UI (2 Schritte: allgemein -> Zonen)."""

    VERSION = 1

    def __init__(self) -> None:
        self._data: dict = {}

    async def async_step_user(self, user_input=None):
        errors: dict[str, str] = {}
        display_defaults = self._data
        if user_input is not None:
            errors = await _validate_entities(self.hass, user_input)
            if not errors:
                self._data.update(user_input)
                return await self.async_step_zones()
            display_defaults = {**self._data, **user_input}

        return self.async_show_form(
            step_id="user",
            data_schema=_build_general_schema(self.hass, display_defaults),
            errors=errors,
        )

    async def async_step_zones(self, user_input=None):
        if user_input is not None:
            self._data.update(user_input)
            return self.async_create_entry(title="ET0 Bewässerung", data=self._data)

        return self.async_show_form(
            step_id="zones",
            data_schema=_build_zone_schema({}),
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return Et0OptionsFlow()


class Et0OptionsFlow(config_entries.OptionsFlow):
    """Spätere Anpassung über Einstellungen -> Geräte & Dienste -> Konfigurieren.

    Wichtig: KEIN eigener __init__ mit `self.config_entry = config_entry`!
    In aktuellen HA-Versionen ist `config_entry` eine reine (read-only)
    Property der Basisklasse - das Zuweisen wirft einen AttributeError.
    self.config_entry ist ab dem ersten async_step_* automatisch verfügbar.
    """

    def __init__(self) -> None:
        self._data: dict = {}

    async def async_step_init(self, user_input=None):
        if not self._data:
            self._data = {**self.config_entry.data, **self.config_entry.options}

        errors: dict[str, str] = {}
        display_defaults = self._data
        if user_input is not None:
            errors = await _validate_entities(self.hass, user_input)
            if not errors:
                self._data.update(user_input)
                return await self.async_step_zones()
            display_defaults = {**self._data, **user_input}

        return self.async_show_form(
            step_id="init",
            data_schema=_build_general_schema(self.hass, display_defaults),
            errors=errors,
        )

    async def async_step_zones(self, user_input=None):
        if user_input is not None:
            self._data.update(user_input)
            return self.async_create_entry(title="", data=self._data)

        return self.async_show_form(
            step_id="zones",
            data_schema=_build_zone_schema(self._data),
        )
