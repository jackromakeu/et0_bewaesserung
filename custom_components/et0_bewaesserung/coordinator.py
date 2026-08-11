"""DataUpdateCoordinator für die ET0-Bewässerungsintegration."""

from __future__ import annotations

import logging
from datetime import date, timedelta

from homeassistant.core import HomeAssistant, callback
from homeassistant.config_entries import ConfigEntry
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.event import async_track_time_change, async_call_later
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util

from .const import (
    DOMAIN,
    STORAGE_VERSION,
    STORAGE_KEY,
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
    ALBEDO,
    MAX_ZONES,
    DEFAULT_ZONE_NAMES,
    DEFAULT_ZONE_KC,
    DEFAULT_ZONE_DRIP_RATE,
    DEFAULT_ZONE_MIN_DAYS,
    DEFAULT_ZONE_MIN_DEFICIT_MM,
    zone_key,
    CONF_RAIN_SKIP_ENABLED,
    CONF_RAIN_SKIP_THRESHOLD,
    DEFAULT_RAIN_SKIP_ENABLED,
    DEFAULT_RAIN_SKIP_THRESHOLD,
    RETRY_DELAY_MINUTES,
    MAX_RETRIES,
    DIAGNOSE_MODE,
    FALLBACK_MAX_AGE_HOURS,
    CONF_FROST_LOOKAHEAD_DAYS,
    DEFAULT_FROST_LOOKAHEAD_DAYS,
    CONF_FROST_THRESHOLD,
    DEFAULT_FROST_THRESHOLD,
    CONF_SPRING_EARLIEST_DATE,
    DEFAULT_SPRING_EARLIEST_DATE,
)
from .et0 import calculate_et0, calculate_etc

_LOGGER = logging.getLogger(__name__)


class Et0Coordinator(DataUpdateCoordinator):
    """Koordiniert die tägliche ET0-Berechnung und die Wasserbilanz je Zone."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(hass, _LOGGER, name=DOMAIN, update_interval=None)
        self.entry = entry
        self._store = Store(hass, STORAGE_VERSION, f"{STORAGE_KEY}_{entry.entry_id}")
        self._deficit = 0.0
        self._zone_deficits: dict[int, float] = {}
        self._last_processed_date: str | None = None
        self._last_known_values: dict[str, dict] = {}
        self._fallback_used_this_run: set[str] = set()
        self._last_watered: dict[int, dict] = {}
        self._today_contribution_global: float = 0.0
        self._today_contribution: dict[int, float] = {}
        self._season_active: bool = True
        self._equipment_stored: bool = False
        self._frost_warning_active: bool = False
        self._spring_ready_active: bool = False
        self._unsub_time = None
        self._unsub_retry = None

    async def async_setup(self) -> None:
        """Lädt gespeicherte Werte und registriert den täglichen Trigger."""
        stored = await self._store.async_load()
        if stored:
            self._deficit = stored.get("deficit", 0.0)
            # Store persistiert als JSON -> Zonen-Keys kommen als Strings zurück
            self._zone_deficits = {
                int(k): v for k, v in stored.get("zone_deficits", {}).items()
            }
            self._last_processed_date = stored.get("last_processed_date")
            self._last_known_values = stored.get("last_known_values", {})
            self._last_watered = {
                int(k): v for k, v in stored.get("last_watered", {}).items()
            }
            self._today_contribution_global = stored.get(
                "today_contribution_global", 0.0
            )
            self._today_contribution = {
                int(k): v for k, v in stored.get("today_contribution", {}).items()
            }
            self._season_active = stored.get("season_active", True)
            self._equipment_stored = stored.get("equipment_stored", False)
            self._frost_warning_active = stored.get("frost_warning_active", False)
            self._spring_ready_active = stored.get("spring_ready_active", False)

        update_time = self.entry.options.get(
            CONF_UPDATE_TIME,
            self.entry.data.get(CONF_UPDATE_TIME, DEFAULT_UPDATE_TIME),
        )
        # Robust gegen "HH:MM" (z.B. von einem Zeit-Picker ohne Sekunden) und
        # "HH:MM:SS" - Sekunden fehlen einfach auf 0 ergänzen.
        time_parts = update_time.split(":")
        h = int(time_parts[0])
        m = int(time_parts[1])
        s = int(time_parts[2]) if len(time_parts) > 2 else 0

        if DIAGNOSE_MODE:
            _LOGGER.warning(
                "ET0 Bewässerung läuft im DIAGNOSE-MODUS: stündlich zu Minute "
                ":%02d:%02d statt nur einmal täglich um %s. Zum Zurückstellen "
                "DIAGNOSE_MODE in const.py auf False setzen!",
                m,
                s,
                update_time,
            )
            self._unsub_time = async_track_time_change(
                self.hass, self._handle_scheduled_update, minute=m, second=s
            )
        else:
            self._unsub_time = async_track_time_change(
                self.hass, self._handle_scheduled_update, hour=h, minute=m, second=s
            )

    def async_unload(self) -> None:
        if self._unsub_time:
            self._unsub_time()
        if self._unsub_retry:
            self._unsub_retry()

    @callback
    def _handle_scheduled_update(self, now) -> None:
        self.hass.async_create_task(self._run_scheduled_with_retry(attempt=1))

    async def _run_scheduled_with_retry(self, attempt: int) -> None:
        """Führt den geplanten Tageslauf aus und versucht es bei Fehlern erneut.

        Ohne das würde z.B. ein HA-Neustart genau um 23:30 (Update, Stromausfall)
        dazu führen, dass eine Quelle kurzzeitig 'unavailable' ist, die Berechnung
        fehlschlägt und der ganze Tag stillschweigend ausgelassen wird.
        """
        await self.async_refresh()
        if self.last_update_success:
            return

        if attempt >= MAX_RETRIES:
            _LOGGER.error(
                "ET0-Berechnung nach %s Versuchen weiterhin fehlgeschlagen - "
                "heutiger Lauf wird ausgelassen. Ursache: %s",
                attempt,
                self.last_exception,
            )
            return

        _LOGGER.warning(
            "ET0-Berechnung fehlgeschlagen (Versuch %s/%s) - nächster Versuch in "
            "%s Minuten. Ursache: %s",
            attempt,
            MAX_RETRIES,
            RETRY_DELAY_MINUTES,
            self.last_exception,
        )

        async def _retry(_now) -> None:
            await self._run_scheduled_with_retry(attempt + 1)

        self._unsub_retry = async_call_later(
            self.hass, RETRY_DELAY_MINUTES * 60, _retry
        )

    def _get_config(self, key, default=None):
        return self.entry.options.get(key, self.entry.data.get(key, default))

    async def _persist(self) -> None:
        """Speichert den kompletten persistenten Zustand an einer Stelle."""
        await self._store.async_save(
            {
                "deficit": self._deficit,
                "zone_deficits": self._zone_deficits,
                "last_processed_date": self._last_processed_date,
                "last_known_values": self._last_known_values,
                "last_watered": self._last_watered,
                "today_contribution_global": self._today_contribution_global,
                "today_contribution": self._today_contribution,
                "season_active": self._season_active,
                "equipment_stored": self._equipment_stored,
                "frost_warning_active": self._frost_warning_active,
                "spring_ready_active": self._spring_ready_active,
            }
        )

    def get_zone_definitions(self) -> list[dict]:
        """Liefert die konfigurierten, aktiven Zonen (leerer Name = deaktiviert)."""
        zones = []
        for i in range(MAX_ZONES):
            name = self._get_config(zone_key(i, "name"), DEFAULT_ZONE_NAMES[i])
            if not name:
                continue
            kc = float(self._get_config(zone_key(i, "kc"), DEFAULT_ZONE_KC[i]))
            drip_rate = float(
                self._get_config(zone_key(i, "drip_rate"), DEFAULT_ZONE_DRIP_RATE[i])
            )
            min_days = int(
                self._get_config(zone_key(i, "min_days"), DEFAULT_ZONE_MIN_DAYS[i])
            )
            min_deficit_mm = float(
                self._get_config(
                    zone_key(i, "min_deficit_mm"), DEFAULT_ZONE_MIN_DEFICIT_MM[i]
                )
            )
            zones.append(
                {
                    "index": i,
                    "name": name,
                    "kc": kc,
                    "drip_rate": drip_rate,
                    "min_days": min_days,
                    "min_deficit_mm": min_deficit_mm,
                }
            )
        return zones

    def _min_interval_status(self, zone_index: int, min_days: int) -> tuple[bool, int | None]:
        """Prüft den Mindestabstand seit der letzten Bewässerung dieser Zone.

        Gibt (mindestabstand_erfuellt, tage_seit_letzter_bewaesserung) zurück.
        Noch nie bewässert -> Abstand gilt als erfüllt (kein künstliches
        Warten vor der allerersten Bewässerung).
        """
        watered_info = self._last_watered.get(zone_index)
        if not watered_info or not watered_info.get("timestamp"):
            return True, None

        last_dt = dt_util.parse_datetime(watered_info["timestamp"])
        if last_dt is None:
            return True, None

        now = dt_util.now()
        days_since = (now.date() - last_dt.astimezone(now.tzinfo).date()).days
        return days_since >= min_days, days_since

    def _get_float_state(self, entity_id: str, daily_reset: bool = False) -> float:
        """Liest eine Entity als float, mit Fallback auf den letzten bekannten Wert.

        daily_reset=True kennzeichnet Tages-Zähler (z.B. PV-Ertrag heute), die
        um Mitternacht auf 0 zurückspringen. Für solche Entities darf der
        Fallback NICHT über eine Mitternachtsgrenze hinweg verwendet werden -
        der Wert von gestern Abend sagt nichts über heute aus und würde sonst
        fälschlich als "heutiger Ertrag" durchgereicht.
        """
        state = self.hass.states.get(entity_id)
        now = dt_util.now()

        value: float | None = None
        problem: str | None = None

        if state is None:
            problem = "nicht gefunden"
        elif state.state in ("unknown", "unavailable", None):
            problem = f"state={state.state}"
        else:
            try:
                value = float(state.state)
            except ValueError:
                problem = f"nicht-numerischer Zustand {state.state!r}"

        if problem is None:
            # Erfolgreich gelesen -> als "letzten bekannten Wert" merken
            self._last_known_values[entity_id] = {
                "value": value,
                "timestamp": now.isoformat(),
            }
            return value

        # --- Live-Wert nicht nutzbar -> Fallback auf letzten bekannten Wert ---
        cached = self._last_known_values.get(entity_id)
        if cached:
            cached_time = dt_util.parse_datetime(cached["timestamp"])
            if cached_time is not None:
                age_hours = (now - cached_time).total_seconds() / 3600
                same_day = cached_time.astimezone(now.tzinfo).date() == now.date()

                fallback_ok = age_hours <= FALLBACK_MAX_AGE_HOURS
                if daily_reset:
                    fallback_ok = fallback_ok and same_day

                if fallback_ok:
                    self._fallback_used_this_run.add(entity_id)
                    _LOGGER.warning(
                        "Entity %s aktuell nicht nutzbar (%s) - verwende letzten "
                        "bekannten Wert %.3f von %s (Alter: %.1fh)",
                        entity_id,
                        problem,
                        cached["value"],
                        cached["timestamp"],
                        age_hours,
                    )
                    return cached["value"]
                if daily_reset and not same_day:
                    _LOGGER.warning(
                        "Diagnose: %s nicht nutzbar (%s) - Fallback-Wert stammt "
                        "von gestern (Tages-Zähler, %s) und wird NICHT verwendet",
                        entity_id,
                        problem,
                        cached["timestamp"],
                    )

        # Kein brauchbarer Fallback vorhanden -> wie bisher fehlschlagen
        _LOGGER.warning(
            "Diagnose: %s nicht nutzbar (%s) und kein aktueller Fallback-Wert "
            "vorhanden (Prüfzeitpunkt=%s)",
            entity_id,
            problem,
            now.isoformat(),
        )
        raise HomeAssistantError(
            f"Entity {entity_id} liefert keinen gültigen Wert ({problem}) "
            "und es existiert kein ausreichend aktueller Fallback-Wert"
        )

    async def _get_forecast_precipitation_tomorrow(self, weather_entity: str) -> float:
        """Vorhergesagter Niederschlag für morgen (mm) über weather.get_forecasts.

        Gibt 0.0 zurück, wenn die Abfrage fehlschlägt oder kein Tageswert für
        morgen gefunden wird - die Regen-Skip-Prüfung ist ein "nice to have"
        und darf den eigentlichen ET0-Lauf niemals zum Absturz bringen.
        """
        try:
            response = await self.hass.services.async_call(
                "weather",
                "get_forecasts",
                service_data={"type": "daily"},
                target={"entity_id": weather_entity},
                blocking=True,
                return_response=True,
            )
        except Exception as err:  # noqa: BLE001 - bewusst breit, siehe Docstring
            _LOGGER.warning("Regenvorhersage konnte nicht abgerufen werden: %s", err)
            return 0.0

        forecasts = (response or {}).get(weather_entity, {}).get("forecast", [])
        tomorrow_iso = (date.today() + timedelta(days=1)).isoformat()

        total = 0.0
        for entry in forecasts:
            entry_date = str(entry.get("datetime", ""))[:10]
            if entry_date == tomorrow_iso:
                total += float(entry.get("precipitation") or 0.0)
        return total

    async def _get_forecast_min_temps(
        self, weather_entity: str, days: int
    ) -> list[float]:
        """Tiefsttemperaturen (°C) der kommenden `days` Tage (inkl. heute).

        Gibt eine leere Liste zurück, wenn die Abfrage fehlschlägt - die
        Frost-Erkennung ist "nice to have" und darf den ET0-Lauf nie stören.
        """
        try:
            response = await self.hass.services.async_call(
                "weather",
                "get_forecasts",
                service_data={"type": "daily"},
                target={"entity_id": weather_entity},
                blocking=True,
                return_response=True,
            )
        except Exception as err:  # noqa: BLE001 - siehe Docstring
            _LOGGER.warning("Frost-Vorhersage konnte nicht abgerufen werden: %s", err)
            return []

        forecasts = (response or {}).get(weather_entity, {}).get("forecast", [])
        today = date.today()
        cutoff = today + timedelta(days=days)

        temps: list[float] = []
        for entry in forecasts:
            entry_date_str = str(entry.get("datetime", ""))[:10]
            try:
                entry_date = date.fromisoformat(entry_date_str)
            except ValueError:
                continue
            if today <= entry_date <= cutoff and entry.get("templow") is not None:
                temps.append(float(entry["templow"]))
        return temps

    async def _async_update_data(self) -> dict:
        self._fallback_used_this_run = set()

        # Momentaufnahme ALLER Eingangs-Entities, bevor einzeln geprüft wird -
        # damit bei einem Fehlschlag nicht nur die eine zuerst scheiternde
        # Entity sichtbar ist, sondern das Gesamtbild zum exakten Zeitpunkt.
        input_entities = {
            "temp_max": self._get_config(CONF_TEMP_MAX_ENTITY),
            "temp_min": self._get_config(CONF_TEMP_MIN_ENTITY),
            "humidity_mean": self._get_config(CONF_HUMIDITY_MEAN_ENTITY),
            "wind_mean": self._get_config(CONF_WIND_MEAN_ENTITY),
            "pv_yield": self._get_config(CONF_PV_YIELD_ENTITY),
        }
        snapshot = {
            label: (self.hass.states.get(eid).state if self.hass.states.get(eid) else "FEHLT")
            for label, eid in input_entities.items()
        }
        _LOGGER.debug(
            "Momentaufnahme Eingangswerte um %s: %s",
            dt_util.now().isoformat(),
            snapshot,
        )

        tmax = self._get_float_state(input_entities["temp_max"])
        tmin = self._get_float_state(input_entities["temp_min"])
        rh_mean = self._get_float_state(input_entities["humidity_mean"])
        wind_mean = self._get_float_state(input_entities["wind_mean"])
        pv_yield = self._get_float_state(input_entities["pv_yield"], daily_reset=True)

        kwp = float(self._get_config(CONF_KWP))
        pr = float(self._get_config(CONF_PERFORMANCE_RATIO))
        latitude = float(self._get_config(CONF_LATITUDE, self.hass.config.latitude))
        elevation = float(self._get_config(CONF_ELEVATION, self.hass.config.elevation))

        result = calculate_et0(
            tmax=tmax,
            tmin=tmin,
            rh_mean=rh_mean,
            wind_mean_kmh=wind_mean,
            pv_yield_kwh=pv_yield,
            kwp=kwp,
            performance_ratio=pr,
            latitude=latitude,
            elevation=elevation,
            albedo=ALBEDO,
        )

        precipitation = 0.0
        weather_entity = self._get_config(CONF_WEATHER_ENTITY)
        if weather_entity:
            weather_state = self.hass.states.get(weather_entity)
            if weather_state:
                precipitation = float(
                    weather_state.attributes.get("precipitation", 0.0) or 0.0
                )

        # --- Vorausschauender Regen-Skip ---
        rain_skip_enabled = bool(
            self._get_config(CONF_RAIN_SKIP_ENABLED, DEFAULT_RAIN_SKIP_ENABLED)
        )
        rain_skip_threshold = float(
            self._get_config(CONF_RAIN_SKIP_THRESHOLD, DEFAULT_RAIN_SKIP_THRESHOLD)
        )
        forecast_precip_mm = 0.0
        if rain_skip_enabled and weather_entity:
            forecast_precip_mm = await self._get_forecast_precipitation_tomorrow(
                weather_entity
            )
        rain_expected = forecast_precip_mm >= rain_skip_threshold

        # --- Frost-/Frühjahrs-Erkennung (unabhängig von der Tages-Sperre,
        #     läuft bei jedem Lauf, damit die Warnung so früh wie möglich
        #     kommt) ---
        frost_lookahead = int(
            self._get_config(CONF_FROST_LOOKAHEAD_DAYS, DEFAULT_FROST_LOOKAHEAD_DAYS)
        )
        frost_threshold = float(
            self._get_config(CONF_FROST_THRESHOLD, DEFAULT_FROST_THRESHOLD)
        )
        spring_earliest = self._get_config(
            CONF_SPRING_EARLIEST_DATE, DEFAULT_SPRING_EARLIEST_DATE
        )

        frost_forecast = False
        if weather_entity:
            min_temps = await self._get_forecast_min_temps(
                weather_entity, frost_lookahead
            )
            frost_forecast = any(t <= frost_threshold for t in min_temps)

        # Herbst: Saison läuft noch, Equipment noch nicht verstaut, Frost kommt
        if self._season_active and not self._equipment_stored and frost_forecast:
            if not self._frost_warning_active:
                _LOGGER.warning(
                    "Frost innerhalb der nächsten %s Tage erwartet (Schwelle %s°C) "
                    "- Equipment-Abbau erforderlich",
                    frost_lookahead,
                    frost_threshold,
                )
            self._frost_warning_active = True

        # Frühjahr: Saison pausiert, Equipment noch verstaut, Datum + Wetter passen
        today_md = date.today().strftime("%m-%d")
        past_earliest = today_md >= spring_earliest
        if (
            not self._season_active
            and self._equipment_stored
            and past_earliest
            and not frost_forecast
        ):
            if not self._spring_ready_active:
                _LOGGER.warning(
                    "Frühjahrsbedingungen erfüllt (ab %s, kein Frost in %s Tagen) "
                    "- Equipment-Wiederaufbau möglich",
                    spring_earliest,
                    frost_lookahead,
                )
            self._spring_ready_active = True

        # --- Tages-Sperre: Bilanz nur EINMAL pro Kalendertag fortschreiben ---
        today_iso = date.today().isoformat()
        is_new_day = self._last_processed_date != today_iso

        if is_new_day:
            # --- Globale Referenzbilanz (Kc=1, Referenzgras) ---
            global_delta = result["et0"] - precipitation
            self._deficit = max(self._deficit + global_delta, -10.0)
            self._today_contribution_global = global_delta
            self._today_contribution = {}

            # --- Bilanz je Zone (Kc-gewichtet) ---
            zones_data: dict[int, dict] = {}
            for zone in self.get_zone_definitions():
                idx = zone["index"]
                etc = calculate_etc(result["et0"], zone["kc"])
                zone_delta = etc - precipitation
                prev_deficit = self._zone_deficits.get(idx, 0.0)
                new_deficit = max(prev_deficit + zone_delta, -10.0)
                self._zone_deficits[idx] = new_deficit
                self._today_contribution[idx] = zone_delta

                min_interval_ok, days_since_watered = self._min_interval_status(
                    idx, zone["min_days"]
                )
                min_deficit_ok = new_deficit >= zone["min_deficit_mm"]
                watering_allowed = (
                    not rain_expected and min_interval_ok and min_deficit_ok
                )

                duration_min = 0.0
                if watering_allowed and zone["drip_rate"] > 0:
                    duration_min = max(new_deficit, 0.0) / zone["drip_rate"]

                watered_info = self._last_watered.get(idx, {})
                zones_data[idx] = {
                    "name": zone["name"],
                    "etc": etc,
                    "deficit": round(new_deficit, 2),
                    "duration_min": round(duration_min, 1),
                    "rain_skip": rain_expected,
                    "min_interval_ok": min_interval_ok,
                    "days_since_watered": days_since_watered,
                    "min_deficit_ok": min_deficit_ok,
                    "watering_allowed": watering_allowed,
                    "last_watered_timestamp": watered_info.get("timestamp"),
                    "last_watered_amount_mm": watered_info.get("amount_mm"),
                    "today_contribution_mm": round(self._today_contribution.get(idx, 0.0), 2),
                }

            self._last_processed_date = today_iso
            await self._persist()
        else:
            # Heute wurde schon gebucht - Bilanz unverändert lassen, aber
            # trotzdem aktuelle Diagnosewerte (ETc je Zone) zur Anzeige liefern
            zones_data = {}
            for zone in self.get_zone_definitions():
                idx = zone["index"]
                etc = calculate_etc(result["et0"], zone["kc"])
                deficit = self._zone_deficits.get(idx, 0.0)
                min_interval_ok, days_since_watered = self._min_interval_status(
                    idx, zone["min_days"]
                )
                min_deficit_ok = deficit >= zone["min_deficit_mm"]
                watering_allowed = (
                    not rain_expected and min_interval_ok and min_deficit_ok
                )
                duration_min = 0.0
                if watering_allowed and zone["drip_rate"] > 0:
                    duration_min = max(deficit, 0.0) / zone["drip_rate"]
                watered_info = self._last_watered.get(idx, {})
                zones_data[idx] = {
                    "name": zone["name"],
                    "etc": etc,
                    "deficit": round(deficit, 2),
                    "duration_min": round(duration_min, 1),
                    "rain_skip": rain_expected,
                    "min_interval_ok": min_interval_ok,
                    "days_since_watered": days_since_watered,
                    "min_deficit_ok": min_deficit_ok,
                    "watering_allowed": watering_allowed,
                    "last_watered_timestamp": watered_info.get("timestamp"),
                    "last_watered_amount_mm": watered_info.get("amount_mm"),
                    "today_contribution_mm": round(self._today_contribution.get(idx, 0.0), 2),
                }
            _LOGGER.debug(
                "ET0-Bilanz heute (%s) bereits gebucht - überspringe erneute Buchung",
                today_iso,
            )
            await self._persist()

        result["deficit"] = round(self._deficit, 2)
        result["precipitation"] = precipitation
        result["rain_expected"] = rain_expected
        result["forecast_precip_mm"] = round(forecast_precip_mm, 1)
        result["zones"] = zones_data
        result["fallback_used"] = sorted(self._fallback_used_this_run)
        result["season_active"] = self._season_active
        result["equipment_stored"] = self._equipment_stored
        result["frost_warning_active"] = self._frost_warning_active
        result["spring_ready_active"] = self._spring_ready_active
        # Diagnose-Transparenz: macht den intern verwendeten Buchungs-Zustand
        # direkt sichtbar, statt ihn aus Verlaufsgraphen rekonstruieren zu
        # müssen (genau das hat uns schon mehrfach in die Irre geführt).
        result["last_processed_date"] = self._last_processed_date
        result["today_contribution_global"] = round(self._today_contribution_global, 2)
        return result

    async def async_force_recalculate(self) -> None:
        """Macht die heutige Buchung (falls vorhanden) gezielt rückgängig und
        löst die Tages-Sperre, damit der nächste Refresh heute nochmal neu
        bucht - z.B. weil ein Testlauf kurz nach Mitternacht mit Rs=0 die
        korrekte Buchung des Tages vorweggenommen hat.

        Im Gegensatz zu einem globalen reset_deficit werden dabei NUR die
        heute tatsächlich hinzugefügten Beiträge abgezogen - die Bilanz
        aus vorangegangenen Tagen bleibt unangetastet.
        """
        today_iso = date.today().isoformat()
        if self._last_processed_date == today_iso:
            self._deficit = max(
                self._deficit - self._today_contribution_global, -10.0
            )
            for idx, delta in self._today_contribution.items():
                current = self._zone_deficits.get(idx, 0.0)
                self._zone_deficits[idx] = max(current - delta, -10.0)

            self._last_processed_date = None
            self._today_contribution_global = 0.0
            self._today_contribution = {}
            await self._persist()
            _LOGGER.info(
                "Heutige Buchung zurückgenommen, Tages-Sperre gelöst - "
                "nächster Refresh bucht neu"
            )
        else:
            _LOGGER.debug(
                "Force-Recalculate: heute wurde noch gar nicht gebucht, "
                "nichts zurückzunehmen"
            )

    async def async_reset_deficit(
        self, zone_index: int | None = None, amount_mm: float | None = None
    ) -> None:
        """Setzt die Wasserbilanz zurück - global (None) oder für eine einzelne Zone.

        Wird eine einzelne Zone mit `amount_mm` zurückgemeldet (der
        Normalfall nach echtem Gießen durch eine Automation), wird diese
        tatsächlich abgegebene Menge vom Defizit ABGEZOGEN statt das
        Defizit hart auf 0 zu setzen. Das ist wichtig für dosisbasierte
        Systeme (z.B. Aiper mit nur 3/6/13mm verfügbar): Bei einem Defizit
        von 4,2mm und einer gewählten Dosis von 3mm bleiben korrekt 1,2mm
        Restdefizit stehen, statt fälschlich verloren zu gehen. Für
        laufzeitbasierte Systeme, die exakt die angeforderte Menge liefern
        (z.B. Tropfschlauch), ergibt das ohnehin dasselbe wie ein Reset auf 0.

        Wird `amount_mm` NICHT angegeben (z.B. manueller Admin-Reset ohne
        genaue Mengenangabe), bleibt das alte Verhalten (hart auf 0) erhalten.

        Ein globaler Reset (zone_index=None, z.B. zur Fehlerkorrektur oder
        beim Saisonwechsel) zählt NICHT als "gegossen" und setzt weiterhin
        immer hart auf 0.
        """
        if zone_index is None:
            self._deficit = 0.0
            self._zone_deficits = {k: 0.0 for k in self._zone_deficits}
            # Tages-Sperre mit lösen: sonst würde die nächste Berechnung (auch
            # sofort danach) denken "heute schon gebucht" und nichts addieren.
            self._last_processed_date = None
        else:
            if amount_mm is not None:
                current = self._zone_deficits.get(zone_index, 0.0)
                self._zone_deficits[zone_index] = max(current - amount_mm, -10.0)
            else:
                self._zone_deficits[zone_index] = 0.0
            self._last_watered[zone_index] = {
                "timestamp": dt_util.now().isoformat(),
                "amount_mm": amount_mm,
            }
        await self._persist()
        await self.async_request_refresh()

    async def async_set_season_active(self, active: bool) -> None:
        """Schaltet die Bewässerungssaison manuell an/aus (switch.gartensaison_aktiv).

        Setzt IMMER die komplette Bilanz zurück (Referenz + alle Zonen),
        damit weder ein künstlicher Rückstau über die Pause anwächst, noch
        beim Reaktivieren sofort ein riesiger Nachhol-Gießschub ausgelöst
        wird. Rührt bewusst NICHT an equipment_stored/frost_warning_active/
        spring_ready_active - das sind unabhängige Angelegenheiten, die nur
        über async_set_equipment_stored gesteuert werden.
        """
        self._season_active = active
        self._deficit = 0.0
        self._zone_deficits = {k: 0.0 for k in self._zone_deficits}
        self._last_processed_date = None
        await self._persist()
        await self.async_request_refresh()

    async def async_set_equipment_stored(self, stored: bool) -> None:
        """Bestätigt, dass das Bewässerungs-Equipment verstaut/aufgebaut wurde.

        Verkettet automatisch mit der Saison: "verstaut" schaltet die Saison
        aus, "aufgebaut" schaltet sie wieder an. Löscht außerdem die jeweils
        zugehörige "sticky" Erinnerungs-Flag, damit die tägliche Nachfrage
        aufhört, bis der nächste Zyklus (nächster Herbst/Frühling) wieder
        eine neue Anfrage auslöst.
        """
        self._equipment_stored = stored
        if stored:
            self._frost_warning_active = False
        else:
            self._spring_ready_active = False
        await self.async_set_season_active(not stored)
