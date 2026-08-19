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
from homeassistant.helpers import issue_registry as ir
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
    CONF_PV_TILT,
    DEFAULT_PV_TILT,
    CONF_PV_AZIMUTH,
    DEFAULT_PV_AZIMUTH,
    CONF_UPDATE_TIME,
    DEFAULT_UPDATE_TIME,
    ALBEDO,
    MAX_ZONES,
    DEFAULT_ZONE_NAMES,
    DEFAULT_ZONE_KC,
    DEFAULT_ZONE_DRIP_RATE,
    DEFAULT_ZONE_MIN_DAYS,
    DEFAULT_ZONE_MIN_DEFICIT_MM,
    DEFAULT_ZONE_FIELD_CAPACITY,
    DEFAULT_ZONE_IRRIGATION_EFFICIENCY,
    zone_key,
    CONF_RAIN_SKIP_ENABLED,
    CONF_RAIN_SKIP_THRESHOLD,
    DEFAULT_RAIN_SKIP_ENABLED,
    DEFAULT_RAIN_SKIP_THRESHOLD,
    CONF_RAIN_SENSOR,
    CONF_RAIN_EFFECTIVENESS,
    DEFAULT_RAIN_EFFECTIVENESS,
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
from .health import evaluate_health

_LOGGER = logging.getLogger(__name__)


class Et0Coordinator(DataUpdateCoordinator):
    """Koordiniert die tägliche ET0-Berechnung und die Wasserbilanz je Zone."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(hass, _LOGGER, name=DOMAIN, update_interval=None)
        self.entry = entry
        self._store = Store(hass, STORAGE_VERSION, f"{STORAGE_KEY}_{entry.entry_id}")
        # --- Datenmodell (seit v1.4.0, ersetzt die additive Buchung + Tages-Sperre) ---
        # Global: _season_et0_carry/_today_et0 bilden KEINE Bilanz mehr,
        #          sondern die reine kumulierte ET0-Verdunstung seit
        #          Saisonstart (Statistik). Zurückgesetzt nur beim
        #          Saisonwechsel - die Bewässerung nutzt ausschließlich die
        #          zonenspezifischen Werte unten.
        # Zonen: carry = aufgelaufenes Defizit ABGESCHLOSSENER Tage, abzüglich
        #          Bewässerung. Das ist die Basis für die morgendliche Bewässerung.
        # today  = ETc minus Niederschlag des LAUFENDEN Tages. Wird bei jeder
        #          Berechnung ÜBERSCHRIEBEN, nie addiert -> beliebig oft
        #          wiederholbar ohne Verfälschung (idempotent). Genau deshalb
        #          ist keine Tages-Sperre mehr nötig.
        # current_day = auf welchen Kalendertag sich "today" bezieht. Beim
        #          Tageswechsel wandert today in carry (Rollover).
        self._season_et0_carry = 0.0
        self._today_et0 = 0.0
        self._zone_carry: dict[int, float] = {}
        self._zone_today: dict[int, float] = {}
        self._current_day: str | None = None
        self._last_known_values: dict[str, dict] = {}
        self._fallback_used_this_run: set[str] = set()
        self._last_watered: dict[int, dict] = {}
        self._season_active: bool = True
        self._equipment_stored: bool = False
        self._frost_warning_active: bool = False
        self._spring_ready_active: bool = False
        self._unsub_time = None
        self._unsub_retry = None
        self._unsub_rollover = None
        self._last_success: str | None = None
        self._last_day_gap: int = 1
        self._fallback_streaks: dict[str, int] = {}
        self._health: dict = {"status": "ok", "issues": []}
        self._known_issue_ids: set[str] = set()
        # Regen-/Frost-Skip: HEUTE ist der über den Rollover fixierte,
        # stabile Wert (bleibt für den ganzen Tag gleich, egal ob eine Zone
        # morgens oder abends gießt). MORGEN wird bei jeder Berechnung frisch
        # ermittelt und übernimmt beim nächsten Tageswechsel die Rolle von
        # HEUTE - exakt dasselbe Prinzip wie carry/today bei der Bilanz.
        self._rain_skip_today: bool = False
        self._rain_skip_tomorrow: bool = False
        self._frost_skip_today: bool = False
        self._frost_skip_tomorrow: bool = False

    async def async_setup(self) -> None:
        """Lädt gespeicherte Werte und registriert den täglichen Trigger."""
        stored = await self._store.async_load()
        if stored:
            self._last_known_values = stored.get("last_known_values", {})
            self._last_watered = {
                int(k): v for k, v in stored.get("last_watered", {}).items()
            }
            self._last_success = stored.get("last_success")
            self._last_day_gap = stored.get("last_day_gap", 1)
            self._fallback_streaks = stored.get("fallback_streaks", {})
            self._season_active = stored.get("season_active", True)
            self._equipment_stored = stored.get("equipment_stored", False)
            self._frost_warning_active = stored.get("frost_warning_active", False)
            self._spring_ready_active = stored.get("spring_ready_active", False)
            self._rain_skip_today = stored.get("rain_skip_today", False)
            self._rain_skip_tomorrow = stored.get("rain_skip_tomorrow", False)
            self._frost_skip_today = stored.get("frost_skip_today", False)
            self._frost_skip_tomorrow = stored.get("frost_skip_tomorrow", False)

            # --- Format-Erkennung über drei Storage-Generationen ---
            # v1.5.0+ : season_et0_carry / zone_carry
            # v1.4.0  : carry_deficit    / zone_carry   (nur umbenannt!)
            # <=v1.3.x: deficit          / zone_deficits (additives Altformat)
            # Wichtig: v1.4.0 und v1.5.0 unterscheiden sich NUR im Namen des
            # globalen Schlüssels - die Zonendaten liegen in beiden unter
            # "zone_carry". Wer das übersieht, verliert beim Update genau
            # diese Zonendaten (Bug in 1.5.0/1.6.0, hier behoben).
            has_v15 = "season_et0_carry" in stored
            has_v14 = "carry_deficit" in stored

            if has_v15 or has_v14:
                self._season_et0_carry = stored.get(
                    "season_et0_carry", stored.get("carry_deficit", 0.0)
                )
                self._today_et0 = stored.get(
                    "today_et0", stored.get("today_deficit", 0.0)
                )
                self._zone_carry = {
                    int(k): v for k, v in stored.get("zone_carry", {}).items()
                }
                self._zone_today = {
                    int(k): v for k, v in stored.get("zone_today", {}).items()
                }
                self._current_day = stored.get("current_day")
                if has_v14 and not has_v15:
                    # Der alte globale Wert war eine Bilanz, keine ET0-Summe
                    # -> als Saisonsumme nicht sinnvoll weiterverwendbar.
                    self._season_et0_carry = 0.0
                    _LOGGER.info(
                        "Storage von v1.4.0 gelesen: Zonen-Defizite übernommen, "
                        "ET0-Saisonsumme startet neu bei 0"
                    )
            else:
                # --- Migration vom alten additiven Format ---
                # Zonen: das alte "zone_deficits" enthielt bereits ALLES inkl.
                # des heutigen Beitrags. Wir übernehmen es als carry und
                # rechnen den bekannten heutigen Beitrag heraus, damit er
                # nicht doppelt zählt (einmal in carry, einmal neu in today).
                old_today_zones = {
                    int(k): v for k, v in stored.get("today_contribution", {}).items()
                }
                old_processed = stored.get("last_processed_date")
                today_iso = date.today().isoformat()

                self._zone_carry = {
                    int(k): v for k, v in stored.get("zone_deficits", {}).items()
                }
                if old_processed == today_iso:
                    for idx, delta in old_today_zones.items():
                        self._zone_carry[idx] = max(
                            self._zone_carry.get(idx, 0.0) - delta, -10.0
                        )
                # Global: der alte Wert war eine (nie zurückgesetzte) Bilanz,
                # nicht die kumulierte Verdunstung. Er lässt sich nicht sinnvoll
                # in eine ET0-Saisonsumme umrechnen -> sauberer Neustart bei 0.
                self._season_et0_carry = 0.0
                self._today_et0 = 0.0
                self._zone_today = {}
                self._current_day = today_iso
                _LOGGER.info(
                    "Datenmodell migriert: Zonen-Defizite übernommen, "
                    "ET0-Saisonsumme startet neu bei 0"
                )

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

        # --- Mitternachts-Rollover ---
        # ZWINGEND nötig: Ohne diesen Timer wandert der Beitrag des
        # abgelaufenen Tages erst beim NÄCHSTEN Berechnungslauf (23:09) nach
        # carry - die Bewässerung um ~5 Uhr würde bis dahin mit einem einen
        # Tag alten Defizit arbeiten. Läuft kurz nach Mitternacht, damit die
        # Gieß-Automation am Morgen den aktuellen Wert vorfindet.
        self._unsub_rollover = async_track_time_change(
            self.hass, self._handle_midnight_rollover, hour=0, minute=0, second=30
        )

    @callback
    def _handle_midnight_rollover(self, now) -> None:
        self.hass.async_create_task(self._async_do_midnight_rollover())

    async def _async_do_midnight_rollover(self) -> None:
        """Schiebt den Tagesbeitrag nach carry und aktualisiert die Sensoren.

        Bewusst OHNE Neuberechnung: Um Mitternacht steht der PV-Ertrag auf 0,
        eine ET0-Berechnung würde hier unbrauchbare Werte liefern. Es werden
        nur die vorhandenen Werte umgebucht.
        """
        if self._rollover_if_needed():
            await self._persist()
            # Sensoren mit dem umgebuchten Stand aktualisieren, ohne die
            # ET0-Werte neu zu berechnen
            if self.data:
                new_data = dict(self.data)
                new_data["season_et0_sum"] = round(
                    self._season_et0_carry + self._today_et0, 2
                )
                new_data["today_contribution_global"] = round(self._today_et0, 2)
                new_data["current_day"] = self._current_day
                zones = dict(new_data.get("zones", {}))
                for idx, zdata in zones.items():
                    carry = self._zone_carry.get(idx, 0.0)
                    zd = dict(zdata)
                    zd["deficit"] = round(carry, 2)
                    zd["deficit_running"] = round(
                        max(carry + self._zone_today.get(idx, 0.0), -10.0), 2
                    )
                    zd["today_contribution_mm"] = round(
                        self._zone_today.get(idx, 0.0), 2
                    )
                    # Regen-/Frost-Skip wurden im Rollover bereits von
                    # "morgen" (gestern ermittelt) zu "heute" übernommen -
                    # genau diese frischen Werte gelten jetzt, nicht die
                    # gestrigen aus dem alten Zonen-Dict.
                    zd["rain_skip"] = self._rain_skip_today
                    zd["frost_skip"] = self._frost_skip_today
                    # Gieß-Freigabe mit dem neuen carry neu bewerten
                    for zone in self.get_zone_definitions():
                        if zone["index"] != idx:
                            continue
                        min_ok, days_since = self._min_interval_status(
                            idx, zone["min_days"]
                        )
                        min_def_ok = carry >= zone["min_deficit_mm"]
                        allowed = (
                            not self._rain_skip_today
                            and not self._frost_skip_today
                            and min_ok
                            and min_def_ok
                        )
                        zd["min_interval_ok"] = min_ok
                        zd["days_since_watered"] = days_since
                        zd["min_deficit_ok"] = min_def_ok
                        zd["watering_allowed"] = allowed
                        eff = zone["irrigation_efficiency"]
                        gross = max(carry, 0.0) / eff if eff > 0 else max(carry, 0.0)
                        zd["gross_mm"] = round(gross, 2)
                        zd["duration_min"] = (
                            round(gross / zone["drip_rate"], 1)
                            if allowed and zone["drip_rate"] > 0
                            else 0.0
                        )
                    zones[idx] = zd
                new_data["zones"] = zones
                self.async_set_updated_data(new_data)

    def async_unload(self) -> None:
        if self._unsub_time:
            self._unsub_time()
        if self._unsub_retry:
            self._unsub_retry()
        if self._unsub_rollover:
            self._unsub_rollover()

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
            _LOGGER.info(
                "Planmäßige ET0-Berechnung erfolgreich (Versuch %s) - "
                "ET0=%.2f mm, Niederschlagsquelle=%s",
                attempt,
                (self.data or {}).get("et0", -1),
                (self.data or {}).get("precipitation_source", "?"),
            )
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
                "season_et0_carry": self._season_et0_carry,
                "today_et0": self._today_et0,
                "zone_carry": self._zone_carry,
                "zone_today": self._zone_today,
                "current_day": self._current_day,
                "last_known_values": self._last_known_values,
                "last_watered": self._last_watered,
                "last_success": self._last_success,
                "last_day_gap": self._last_day_gap,
                "fallback_streaks": self._fallback_streaks,
                "season_active": self._season_active,
                "equipment_stored": self._equipment_stored,
                "frost_warning_active": self._frost_warning_active,
                "spring_ready_active": self._spring_ready_active,
                "rain_skip_today": self._rain_skip_today,
                "rain_skip_tomorrow": self._rain_skip_tomorrow,
                "frost_skip_today": self._frost_skip_today,
                "frost_skip_tomorrow": self._frost_skip_tomorrow,
            }
        )

    def _rollover_if_needed(self) -> bool:
        """Schiebt beim Tageswechsel "today" nach "carry".

        Wird bei JEDER Berechnung aufgerufen (nicht per Timer), damit ein
        verpasster Mitternachts-Zeitpunkt - z.B. weil HA gerade neu startete,
        ein Update lief oder der Strom weg war - beim nächsten Lauf
        automatisch nachgeholt wird. Genau dieses Ausfallrisiko war der
        Hauptkritikpunkt am reinen Timer-Ansatz.
        """
        today_iso = date.today().isoformat()
        if self._current_day == today_iso:
            return False

        if self._current_day is not None:
            # Wie viele Tage liegen zwischen dem letzten gebuchten Tag und
            # heute? 1 = normal, >1 = Buchungslücke (HA war aus, Timer fehlte)
            try:
                prev = date.fromisoformat(self._current_day)
                self._last_day_gap = max((date.today() - prev).days, 1)
            except (ValueError, TypeError):
                self._last_day_gap = 1
            self._season_et0_carry = self._season_et0_carry + self._today_et0
            # Obergrenze = nutzbare Feldkapazität der Wurzelzone. Mehr Wasser
            # als das kann der Boden nicht halten - ein darüber hinaus
            # aufgelaufenes Defizit würde eine Bewässerungsmenge fordern, die
            # größtenteils unterhalb der Wurzeln versickert. Ohne Deckel wächst
            # das Defizit z.B. über einen Urlaub unbegrenzt weiter.
            capacities = {
                z["index"]: z["field_capacity_mm"]
                for z in self.get_zone_definitions()
            }
            for idx, val in self._zone_today.items():
                neu = self._zone_carry.get(idx, 0.0) + val
                cap = capacities.get(idx)
                if cap is not None and neu > cap:
                    _LOGGER.info(
                        "Zone %s: Defizit auf Feldkapazität begrenzt "
                        "(%.2f -> %.2f mm)",
                        idx,
                        neu,
                        cap,
                    )
                    neu = cap
                self._zone_carry[idx] = max(neu, -10.0)
            _LOGGER.info(
                "Tageswechsel %s -> %s: today (%.2f mm) nach carry übernommen "
                "(neu: %.2f mm)",
                self._current_day,
                today_iso,
                self._today_et0,
                self._season_et0_carry,
            )

            # Regen-/Frost-Skip: die für "morgen" (= jetzt heute) ermittelte
            # Einschätzung wird übernommen und bleibt bis zum nächsten
            # Tageswechsel stabil - unabhängig davon, ob eine Zone morgens
            # oder abends gießt. Automationen fragen ausschließlich "heute" ab.
            self._rain_skip_today = self._rain_skip_tomorrow
            self._frost_skip_today = self._frost_skip_tomorrow

        self._today_et0 = 0.0
        self._zone_today = {}
        self._current_day = today_iso
        return True

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
            field_capacity = float(
                self._get_config(
                    zone_key(i, "field_capacity_mm"), DEFAULT_ZONE_FIELD_CAPACITY[i]
                )
            )
            irrigation_efficiency = float(
                self._get_config(
                    zone_key(i, "irrigation_efficiency"),
                    DEFAULT_ZONE_IRRIGATION_EFFICIENCY[i],
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
                    "field_capacity_mm": field_capacity,
                    "irrigation_efficiency": irrigation_efficiency,
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

    async def _get_forecast_precipitation(
        self, weather_entity: str, target_date: date
    ) -> float:
        """Vorhergesagter/prognostizierter Tagesniederschlag (mm) für target_date.

        Wird für zwei Zwecke genutzt:
        - target_date = morgen  -> Regen-Skip (soll morgen gegossen werden?)
        - target_date = heute   -> Niederschlagsabzug in der Tagesbilanz

        Gibt 0.0 zurück, wenn die Abfrage fehlschlägt - die Regen-Logik ist
        ein "nice to have" und darf den ET0-Lauf nie zum Absturz bringen.
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
        target_iso = target_date.isoformat()

        total = 0.0
        for entry in forecasts:
            entry_date = str(entry.get("datetime", ""))[:10]
            if entry_date == target_iso:
                total += float(entry.get("precipitation") or 0.0)
        return total

    async def _get_forecast_min_temp_for(
        self, weather_entity: str, target_date: date
    ) -> float | None:
        """Tiefsttemperatur (°C) für einen konkreten Tag, None wenn unbekannt."""
        try:
            response = await self.hass.services.async_call(
                "weather",
                "get_forecasts",
                service_data={"type": "daily"},
                target={"entity_id": weather_entity},
                blocking=True,
                return_response=True,
            )
        except Exception as err:  # noqa: BLE001
            _LOGGER.warning("Frost-Vorhersage nicht abrufbar: %s", err)
            return None

        target_iso = target_date.isoformat()
        for entry in (response or {}).get(weather_entity, {}).get("forecast", []):
            if str(entry.get("datetime", ""))[:10] == target_iso:
                low = entry.get("templow")
                return float(low) if low is not None else None
        return None

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
            tilt=float(self._get_config(CONF_PV_TILT, DEFAULT_PV_TILT)),
            azimuth=float(self._get_config(CONF_PV_AZIMUTH, DEFAULT_PV_AZIMUTH)),
        )

        # --- Niederschlag des HEUTIGEN Tages für die Bilanz ---
        # Priorität: gemessener Wert (eigene Wetterstation) > Tagessumme aus
        # der Vorhersage. Der frühere Ansatz las das "precipitation"-Attribut
        # der weather-Entity - das ist aber ein Momentan-/Prognosewert des
        # aktuellen Intervalls, kein Tagesniederschlag: ein Gewitter um 15 Uhr
        # war um 23 Uhr längst nicht mehr sichtbar und fehlte in der Bilanz.
        weather_entity = self._get_config(CONF_WEATHER_ENTITY)
        rain_sensor = self._get_config(CONF_RAIN_SENSOR)
        rain_effectiveness = float(
            self._get_config(CONF_RAIN_EFFECTIVENESS, DEFAULT_RAIN_EFFECTIVENESS)
        )

        precipitation_raw = 0.0
        precipitation_source = "keine"
        if rain_sensor:
            try:
                # WICHTIG: kein daily_reset=True hier! Das Flag ist für
                # Mitternachts-Zähler (PV-Ertrag) gedacht und verbietet dort
                # zurecht einen Fallback über die Tagesgrenze hinweg. Der
                # DWD-Regensensor ist aber ein ROLLIERENDES 24h-Fenster, kein
                # Mitternachts-Zähler - ein wenige Stunden alter Fallback
                # bleibt auch über Mitternacht hinweg sinnvoll. Mit
                # daily_reset=True hätte ein kurzer Ausfall des Sensors kurz
                # vor der abendlichen Berechnung den Fallback fälschlich
                # verworfen, sobald der gecachte Wert noch vom Vortag war.
                precipitation_raw = self._get_float_state(rain_sensor)
                precipitation_source = "gemessen"
            except HomeAssistantError as err:
                _LOGGER.warning(
                    "Regen-Messsensor %s nicht nutzbar (%s) - weiche auf die "
                    "Vorhersage aus",
                    rain_sensor,
                    err,
                )
        if precipitation_source == "keine" and weather_entity:
            precipitation_raw = await self._get_forecast_precipitation(
                weather_entity, date.today()
            )
            precipitation_source = "prognose"

        # Wirksamkeitsfaktor: nicht jeder mm Regen erreicht die Wurzelzone
        # (Oberflächenabfluss bei Starkregen).
        precipitation = precipitation_raw * rain_effectiveness

        # --- Vorausschauender Regen-Skip: HEUTE und MORGEN getrennt ---
        # "heute" ist der über den Rollover fixierte, für den ganzen Tag
        # stabile Wert (siehe _rollover_if_needed) - Automationen fragen NUR
        # diesen ab, unabhängig davon ob morgens oder abends gegossen wird.
        # "morgen" wird bei jeder Berechnung frisch ermittelt und übernimmt
        # beim nächsten Tageswechsel die Rolle von "heute".
        rain_skip_enabled = bool(
            self._get_config(CONF_RAIN_SKIP_ENABLED, DEFAULT_RAIN_SKIP_ENABLED)
        )
        rain_skip_threshold = float(
            self._get_config(CONF_RAIN_SKIP_THRESHOLD, DEFAULT_RAIN_SKIP_THRESHOLD)
        )
        forecast_precip_today_mm = 0.0
        forecast_precip_tomorrow_mm = 0.0
        if rain_skip_enabled and weather_entity:
            forecast_precip_today_mm = await self._get_forecast_precipitation(
                weather_entity, date.today()
            )
            forecast_precip_tomorrow_mm = await self._get_forecast_precipitation(
                weather_entity, date.today() + timedelta(days=1)
            )
            self._rain_skip_today = forecast_precip_today_mm >= rain_skip_threshold
            self._rain_skip_tomorrow = (
                forecast_precip_tomorrow_mm >= rain_skip_threshold
            )
        rain_expected = self._rain_skip_today

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

            # Frostschutz WÄHREND der Saison, getrennt nach HEUTE/MORGEN wie
            # beim Regen-Skip (siehe dort für die Begründung). Der obige
            # frost_forecast dient einem anderen Zweck (Equipment-Abbau,
            # mehrtägige Vorwarnzeit) und bleibt unverändert.
            temp_today = await self._get_forecast_min_temp_for(
                weather_entity, date.today()
            )
            temp_tomorrow = await self._get_forecast_min_temp_for(
                weather_entity, date.today() + timedelta(days=1)
            )
            self._frost_skip_today = (
                temp_today is not None and temp_today <= frost_threshold
            )
            self._frost_skip_tomorrow = (
                temp_tomorrow is not None and temp_tomorrow <= frost_threshold
            )
        frost_imminent = self._frost_skip_today

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

        # --- Rollover prüfen (holt einen verpassten Tageswechsel nach) ---
        self._rollover_if_needed()

        # --- IDEMPOTENTE Berechnung: "today" wird ÜBERSCHRIEBEN, nie addiert.
        #     Dadurch ist beliebig häufiges Neuberechnen am selben Tag
        #     unschädlich - eine Tages-Sperre ist nicht mehr nötig. ---
        self._today_et0 = result["et0"]

        zones_data: dict[int, dict] = {}
        for zone in self.get_zone_definitions():
            idx = zone["index"]
            etc = calculate_etc(result["et0"], zone["kc"])
            self._zone_today[idx] = etc - precipitation

            carry = self._zone_carry.get(idx, 0.0)
            # Basis fürs Gießen = abgeschlossene Tage. Der laufende Tag ist
            # erst am Abend vollständig und fließt beim Rollover ein.
            deficit_for_watering = carry
            deficit_running = max(carry + self._zone_today[idx], -10.0)

            min_interval_ok, days_since_watered = self._min_interval_status(
                idx, zone["min_days"]
            )
            min_deficit_ok = deficit_for_watering >= zone["min_deficit_mm"]
            watering_allowed = (
                not rain_expected
                and not frost_imminent
                and min_interval_ok
                and min_deficit_ok
            )

            # Auszubringende BRUTTO-Menge: Ein Teil erreicht die Wurzelzone
            # nie (Windabdrift, Verdunstung, ungleiche Verteilung). Um ein
            # Defizit von X mm tatsächlich zu decken, muss X / Wirkungsgrad
            # ausgebracht werden.
            efficiency = zone["irrigation_efficiency"]
            gross_mm = (
                max(deficit_for_watering, 0.0) / efficiency
                if efficiency > 0
                else max(deficit_for_watering, 0.0)
            )

            duration_min = 0.0
            if watering_allowed and zone["drip_rate"] > 0:
                duration_min = gross_mm / zone["drip_rate"]

            watered_info = self._last_watered.get(idx, {})
            zones_data[idx] = {
                "name": zone["name"],
                "etc": etc,
                "deficit": round(deficit_for_watering, 2),
                "gross_mm": round(gross_mm, 2),
                "deficit_running": round(deficit_running, 2),
                "today_contribution_mm": round(self._zone_today[idx], 2),
                "duration_min": round(duration_min, 1),
                "rain_skip": rain_expected,
                "frost_skip": frost_imminent,
                "min_interval_ok": min_interval_ok,
                "days_since_watered": days_since_watered,
                "min_deficit_ok": min_deficit_ok,
                "watering_allowed": watering_allowed,
                "last_watered_timestamp": watered_info.get("timestamp"),
                "last_watered_amount_mm": watered_info.get("amount_mm"),
            }

        await self._persist()

        result["season_et0_sum"] = round(
            self._season_et0_carry + self._today_et0, 2
        )
        result["today_contribution_global"] = round(self._today_et0, 2)
        result["current_day"] = self._current_day
        result["precipitation"] = round(precipitation, 2)
        result["precipitation_raw"] = round(precipitation_raw, 2)
        result["precipitation_source"] = precipitation_source
        result["rain_expected"] = rain_expected
        result["frost_imminent"] = frost_imminent
        result["forecast_precip_mm"] = round(forecast_precip_tomorrow_mm, 1)
        result["rain_skip_tomorrow"] = self._rain_skip_tomorrow
        result["frost_skip_tomorrow"] = self._frost_skip_tomorrow
        result["forecast_precip_today_mm"] = round(forecast_precip_today_mm, 1)
        result["forecast_precip_tomorrow_mm"] = round(forecast_precip_tomorrow_mm, 1)
        result["zones"] = zones_data
        result["fallback_used"] = sorted(self._fallback_used_this_run)
        result["season_active"] = self._season_active
        result["equipment_stored"] = self._equipment_stored
        result["frost_warning_active"] = self._frost_warning_active
        result["spring_ready_active"] = self._spring_ready_active

        # --- Fallback-Streaks fortschreiben ---
        # Quellen, die in diesem Lauf über den Cache liefen, hochzählen;
        # alle anderen zurücksetzen. So fällt eine dauerhaft tote Quelle auf,
        # ein einzelner Aussetzer aber nicht.
        for entity_id in list(self._fallback_streaks):
            if entity_id not in self._fallback_used_this_run:
                del self._fallback_streaks[entity_id]
        for entity_id in self._fallback_used_this_run:
            self._fallback_streaks[entity_id] = (
                self._fallback_streaks.get(entity_id, 0) + 1
            )

        self._last_success = dt_util.now().isoformat()

        # --- Gesundheitsprüfung ---
        self._health = evaluate_health(
            now=dt_util.now(),
            last_success=dt_util.parse_datetime(self._last_success),
            current_day=self._current_day,
            day_gap=self._last_day_gap,
            et0=result.get("et0"),
            calc_date=date.today(),
            fallback_streaks=self._fallback_streaks,
            season_active=self._season_active,
        )
        result["health_status"] = self._health["status"]
        result["health_issues"] = self._health["issues"]
        self._sync_repair_issues()

        await self._persist()
        return result

    def _sync_repair_issues(self) -> None:
        """Spiegelt die Befunde in die HA-Reparaturen-Ansicht.

        Repair Issues sind der von Home Assistant vorgesehene Weg, damit eine
        Integration auf Probleme aufmerksam macht: prominent sichtbar, aber
        nicht aufdringlich wie eine Push-Nachricht - und sie verschwinden
        automatisch wieder, sobald das Problem behoben ist.
        """
        active_codes = set()
        for issue in self._health["issues"]:
            code = issue["code"]
            issue_id = f"{self.entry.entry_id}_{code}"
            active_codes.add(issue_id)
            ir.async_create_issue(
                self.hass,
                DOMAIN,
                issue_id,
                is_fixable=False,
                severity=(
                    ir.IssueSeverity.ERROR
                    if issue["severity"] == "fehler"
                    else ir.IssueSeverity.WARNING
                ),
                translation_key="health_generic",
                translation_placeholders={"details": issue["message"]},
            )

        # Behobene Befunde wieder entfernen
        for issue_id in list(self._known_issue_ids - active_codes):
            ir.async_delete_issue(self.hass, DOMAIN, issue_id)
        self._known_issue_ids = active_codes

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
        immer hart auf 0 - inklusive des laufenden Tages.
        """
        if zone_index is None:
            self._season_et0_carry = 0.0
            self._today_et0 = 0.0
            self._zone_carry = {k: 0.0 for k in self._zone_carry}
            self._zone_today = {}
        else:
            # Bewässerung reduziert die Basis abgeschlossener Tage (carry) -
            # das ist der Wert, auf dem die Gieß-Entscheidung beruht.
            if amount_mm is not None:
                current = self._zone_carry.get(zone_index, 0.0)
                self._zone_carry[zone_index] = max(current - amount_mm, -10.0)
            else:
                self._zone_carry[zone_index] = 0.0
            self._last_watered[zone_index] = {
                "timestamp": dt_util.now().isoformat(),
                "amount_mm": amount_mm,
            }
        await self._persist()
        await self.async_request_refresh()

    async def async_set_season_active(self, active: bool) -> None:
        """Schaltet die Bewässerungssaison manuell an/aus (switch.gartensaison_aktiv).

        Setzt IMMER die komplette Bilanz zurück (Referenz + alle Zonen,
        carry UND laufender Tag), damit weder ein künstlicher Rückstau über
        die Pause anwächst, noch beim Reaktivieren sofort ein riesiger
        Nachhol-Gießschub ausgelöst wird. Rührt bewusst NICHT an
        equipment_stored/frost_warning_active/spring_ready_active - das sind
        unabhängige Angelegenheiten, die nur über async_set_equipment_stored
        gesteuert werden.
        """
        self._season_active = active
        self._season_et0_carry = 0.0
        self._today_et0 = 0.0
        self._zone_carry = {k: 0.0 for k in self._zone_carry}
        self._zone_today = {}
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
