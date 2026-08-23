"""Config Flow für die ET0-Bewässerungsintegration."""

from __future__ import annotations

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.config_entries import ConfigSubentryFlow, SubentryFlowResult
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
    CONF_PV_TILT,
    DEFAULT_PV_TILT,
    CONF_PV_AZIMUTH,
    DEFAULT_PV_AZIMUTH,
    SUBENTRY_TYPE_ZONE,
    CONF_ZONE_NAME,
    CONF_ZONE_KC,
    CONF_ZONE_DRIP_RATE,
    CONF_ZONE_MIN_DAYS,
    CONF_ZONE_MIN_DEFICIT_MM,
    CONF_ZONE_FIELD_CAPACITY,
    CONF_ZONE_IRRIGATION_EFFICIENCY,
    DEFAULT_ZONE_KC,
    DEFAULT_ZONE_DRIP_RATE,
    DEFAULT_ZONE_MIN_DAYS,
    DEFAULT_ZONE_MIN_DEFICIT_MM,
    DEFAULT_ZONE_FIELD_CAPACITY,
    DEFAULT_ZONE_IRRIGATION_EFFICIENCY,
    CONF_RAIN_SKIP_ENABLED,
    CONF_RAIN_SKIP_THRESHOLD,
    DEFAULT_RAIN_SKIP_ENABLED,
    DEFAULT_RAIN_SKIP_THRESHOLD,
    CONF_RAIN_SENSOR,
    CONF_RAIN_EFFECTIVENESS,
    DEFAULT_RAIN_EFFECTIVENESS,
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


def _optional_entity_key(conf_key: str, defaults: dict):
    """Erzeugt einen wirklich optionalen Entity-Feld-Key.

    WICHTIG: Kein `default=""` verwenden - ein leerer String ist für den
    EntitySelector kein gültiger Wert, wodurch das Formular sich nicht mehr
    speichern lässt, solange das Feld leer bleibt. Stattdessen wird der
    bestehende Wert nur als `suggested_value` vorbelegt; bleibt das Feld
    leer, fehlt der Schlüssel im Ergebnis - genau das gewünschte Verhalten
    für ein optionales Feld.
    """
    current = defaults.get(conf_key)
    if current:
        return vol.Optional(conf_key, description={"suggested_value": current})
    return vol.Optional(conf_key)


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
            _optional_entity_key(CONF_WEATHER_ENTITY, defaults): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="weather")
            ),
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
                CONF_PV_TILT, default=defaults.get(CONF_PV_TILT, DEFAULT_PV_TILT)
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(min=0, max=90, step=1, mode="box")
            ),
            vol.Required(
                CONF_PV_AZIMUTH,
                default=defaults.get(CONF_PV_AZIMUTH, DEFAULT_PV_AZIMUTH),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(min=-180, max=180, step=1, mode="box")
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
            _optional_entity_key(CONF_RAIN_SENSOR, defaults): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="sensor")
            ),
            vol.Required(
                CONF_RAIN_EFFECTIVENESS,
                default=defaults.get(
                    CONF_RAIN_EFFECTIVENESS, DEFAULT_RAIN_EFFECTIVENESS
                ),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(min=0.1, max=1.0, step=0.05, mode="box")
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


def _build_zone_schema(defaults: dict) -> vol.Schema:
    """Schema für EINE Zone - sieben Felder statt einer Sammelliste."""
    return vol.Schema(
        {
            vol.Required(
                CONF_ZONE_NAME,
                description={"suggested_value": defaults.get(CONF_ZONE_NAME, "")},
            ): str,
            vol.Required(
                CONF_ZONE_KC,
                default=defaults.get(CONF_ZONE_KC, DEFAULT_ZONE_KC),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(min=0.1, max=1.5, step=0.05, mode="box")
            ),
            vol.Required(
                CONF_ZONE_DRIP_RATE,
                default=defaults.get(CONF_ZONE_DRIP_RATE, DEFAULT_ZONE_DRIP_RATE),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(min=0.01, max=5.0, step=0.01, mode="box")
            ),
            vol.Required(
                CONF_ZONE_MIN_DAYS,
                default=defaults.get(CONF_ZONE_MIN_DAYS, DEFAULT_ZONE_MIN_DAYS),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(min=1, max=14, step=1, mode="box")
            ),
            vol.Required(
                CONF_ZONE_MIN_DEFICIT_MM,
                default=defaults.get(
                    CONF_ZONE_MIN_DEFICIT_MM, DEFAULT_ZONE_MIN_DEFICIT_MM
                ),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(min=0, max=20, step=0.5, mode="box")
            ),
            vol.Required(
                CONF_ZONE_FIELD_CAPACITY,
                default=defaults.get(
                    CONF_ZONE_FIELD_CAPACITY, DEFAULT_ZONE_FIELD_CAPACITY
                ),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(min=5, max=60, step=1, mode="box")
            ),
            vol.Required(
                CONF_ZONE_IRRIGATION_EFFICIENCY,
                default=defaults.get(
                    CONF_ZONE_IRRIGATION_EFFICIENCY,
                    DEFAULT_ZONE_IRRIGATION_EFFICIENCY,
                ),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(min=0.3, max=1.0, step=0.05, mode="box")
            ),
        }
    )


class ZoneSubentryFlowHandler(ConfigSubentryFlow):
    """Anlegen und Bearbeiten einer einzelnen Bewässerungszone.

    Jede Zone ist ein eigener Subentry mit eigenem Gerät. Dadurch gibt es
    keine feste Obergrenze mehr (früher MAX_ZONES = 3), und der Dialog zeigt
    nur die sieben Felder DIESER Zone statt einer langen Sammelliste.
    """

    async def async_step_user(self, user_input=None) -> SubentryFlowResult:
        return await self._async_zone_form(user_input, is_new=True)

    async def async_step_reconfigure(self, user_input=None) -> SubentryFlowResult:
        return await self._async_zone_form(user_input, is_new=False)

    async def _async_zone_form(self, user_input, is_new: bool) -> SubentryFlowResult:
        errors: dict[str, str] = {}
        defaults: dict = {} if is_new else dict(self._get_reconfigure_subentry().data)

        if user_input is not None:
            name = (user_input.get(CONF_ZONE_NAME) or "").strip()
            if not name:
                errors[CONF_ZONE_NAME] = "zone_name_required"
            else:
                user_input[CONF_ZONE_NAME] = name
                if is_new:
                    return self.async_create_entry(title=name, data=user_input)
                return self.async_update_and_abort(
                    self._get_entry(),
                    self._get_reconfigure_subentry(),
                    title=name,
                    data=user_input,
                )
            defaults = {**defaults, **user_input}

        return self.async_show_form(
            step_id="user" if is_new else "reconfigure",
            data_schema=_build_zone_schema(defaults),
            errors=errors,
        )


class Et0ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Ersteinrichtung: nur noch die zonenunabhängigen Einstellungen.

    Zonen werden anschließend einzeln als Subentries hinzugefügt
    ("Zone hinzufügen" auf der Integrationsseite).
    """

    VERSION = 2

    async def async_step_user(self, user_input=None):
        errors: dict[str, str] = {}
        display_defaults: dict = {}
        if user_input is not None:
            errors = await _validate_entities(self.hass, user_input)
            if not errors:
                return self.async_create_entry(
                    title="ET0 Bewässerung", data=user_input
                )
            display_defaults = user_input

        return self.async_show_form(
            step_id="user",
            data_schema=_build_general_schema(self.hass, display_defaults),
            errors=errors,
        )

    @classmethod
    @callback
    def async_get_supported_subentry_types(
        cls, config_entry: config_entries.ConfigEntry
    ) -> dict[str, type[ConfigSubentryFlow]]:
        return {SUBENTRY_TYPE_ZONE: ZoneSubentryFlowHandler}

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return Et0OptionsFlow()


class Et0OptionsFlow(config_entries.OptionsFlow):
    """Anpassung der zonenunabhängigen Einstellungen.

    Wichtig: KEIN eigener __init__ mit `self.config_entry = config_entry`!
    In aktuellen HA-Versionen ist `config_entry` eine reine (read-only)
    Property der Basisklasse - das Zuweisen wirft einen AttributeError.
    """

    async def async_step_init(self, user_input=None):
        current = {**self.config_entry.data, **self.config_entry.options}
        errors: dict[str, str] = {}
        display_defaults = current

        if user_input is not None:
            errors = await _validate_entities(self.hass, user_input)
            if not errors:
                return self.async_create_entry(title="", data=user_input)
            display_defaults = {**current, **user_input}

        return self.async_show_form(
            step_id="init",
            data_schema=_build_general_schema(self.hass, display_defaults),
            errors=errors,
        )
