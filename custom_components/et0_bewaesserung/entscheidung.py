"""Gieß-Entscheidung je Zone: Prioritätskette und Begründung im Klartext.

Bewusst als reine Funktionen ohne Home-Assistant-Abhängigkeiten gehalten -
genau wie et0.py und health.py -, damit die Kette isoliert testbar bleibt.

Warum die Kette überhaupt hier liegt und nicht im Dashboard: Die Reihenfolge
Saison -> Frost -> Regen -> Mindestabstand -> Mindestdefizit stand bisher als
Jinja-Template im Lovelace-Markdown und ein zweites Mal implizit in den
Bedingungen des Dispatchers. Zwei Kopien derselben Regel laufen auseinander,
sobald eine davon angepasst wird. Die Entscheidung entsteht deshalb dort, wo
die Schwellenwerte bekannt sind; das Dashboard zeigt sie nur noch an.

Der Klartext in "grund" ist dieselbe Zeichenkette, die auch eine
Push-Nachricht oder eine TTS-Ansage verwenden kann - die Begründung wird
einmal formuliert und nicht pro Ausgabekanal neu.

WICHTIG - was diese Datei NICHT entscheidet: Sie bewertet nur, ob eine Zone
gegossen wird. Die Equipment-Themen (Frühjahr bereit, Abbau nötig) sind keine
Gieß-Entscheidung, sondern eine Aufforderung an den Menschen, und bleiben
deshalb aus der Kette heraus - sie gehören ins Lagebild, nicht in die
Zonenkarte.
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta

# --- Entscheidungswerte (Prioritätskette von oben nach unten) ---
PAUSIERT = "pausiert"          # Saison aus
UNBEKANNT = "unbekannt"        # keine gültige Berechnung -> im Zweifel nicht gießen
AUSGESETZT = "ausgesetzt"      # Regen oder Frost erwartet
SPERRE = "sperre"              # Mindestabstand seit letztem Lauf nicht erfüllt
WARTET = "wartet"              # Defizit unter Schwelle
LAEUFT = "laeuft"              # wird beim nächsten Dispatcher-Lauf gegossen

ALLE_ENTSCHEIDUNGEN = (PAUSIERT, UNBEKANNT, AUSGESETZT, SPERRE, WARTET, LAEUFT)

# Unter dieser Tages-ETc ist eine Hochrechnung "in X Tagen erreicht" sinnlos -
# bei nahezu null Verdunstung ergäbe sich eine absurd große Tageszahl.
MIN_ETC_FUER_PROGNOSE = 0.05


def _tage_nominativ(anzahl: int) -> str:
    """'1 Tag' / '3 Tage' - für 'Mindestabstand 3 Tage'."""
    return "1 Tag" if anzahl == 1 else f"{anzahl} Tage"


def _tage_dativ(anzahl: int) -> str:
    """'1 Tag' / '3 Tagen' - für 'vor 3 Tagen' und 'in 3 Tagen'."""
    return "1 Tag" if anzahl == 1 else f"{anzahl} Tagen"


def _mm(wert) -> str:
    """Formatiert eine mm-Angabe mit einer Dezimalstelle, robust gegen None."""
    if wert is None:
        return "?"
    return f"{float(wert):.1f}".replace(".", ",")


def _zeitpunkt(moment: datetime | None) -> str | None:
    return moment.strftime("%d.%m. %H:%M") if moment is not None else None


def _sperre_status(
    letzter_lauf: datetime | None, mindestabstand_tage: int, heute
) -> tuple[str | None, int | None]:
    """Ab wann der Mindestabstand wieder erfüllt ist.

    Gibt (frei_ab als "TT.MM.", verbleibende Tage) zurück. Bewusst ein DATUM
    und keine Uhrzeit: Der Mindestabstand rechnet in ganzen Tagen, und wann
    tatsächlich gegossen wird, entscheidet die Automation - eine Uhrzeit wäre
    hier eine erfundene Genauigkeit.
    """
    if letzter_lauf is None:
        return None, None
    frei_ab = letzter_lauf.date() + timedelta(days=mindestabstand_tage)
    return frei_ab.strftime("%d.%m."), max((frei_ab - heute).days, 0)


def entscheide_zonen(
    *,
    now: datetime,
    season_active: bool,
    equipment_stored: bool,
    berechnung_fehlt: bool,
    regen_prognose_mm: float | None,
    zonen: dict[str, dict],
    zonen_config: dict[str, dict],
    letzte_bewaesserung: dict[str, dict],
) -> dict:
    """Bewertet alle Zonen und liefert das Attribut-Dict für den Sensor.

    Argumente:
        zonen: das fertige zones-Dict des Coordinators (deficit, rain_skip, ...)
        zonen_config: {zone_id: {name, min_days, min_deficit_mm}} - die
            AUFGELÖSTEN Betriebswerte, also inklusive der number-Entities
        letzte_bewaesserung: {zone_id: {"timestamp": datetime|None,
            "amount_mm": float|None}} - bereits geparst, damit dieses Modul
            HA-frei bleibt
        berechnung_fehlt: True, wenn die Anzeige aus dem Notbehelf stammt
            (kein erfolgreicher Lauf) - dann ist jede Aussage über heute
            geraten und die Zone bekommt UNBEKANNT statt einer falschen
            Begründung

    Rückgabe:
        {"stand": "TT.MM. HH:MM", "laeuft_anzahl": int, "zonen": {...}}
    """
    heute = now.date()
    ergebnis: dict[str, dict] = {}

    for zone_id, zone in (zonen or {}).items():
        config = (zonen_config or {}).get(zone_id)
        if config is None:
            # Zone wurde zwischen Berechnung und Anzeige entfernt - nichts
            # erfinden, sondern auslassen.
            continue

        schwelle = float(config["min_deficit_mm"])
        mindestabstand = int(config["min_days"])
        defizit = zone.get("deficit")
        etc = zone.get("etc")
        tage_seit = zone.get("days_since_watered")

        gegossen = (letzte_bewaesserung or {}).get(zone_id) or {}
        letzter_lauf_dt = gegossen.get("timestamp")
        frei_ab, tage_bis_freigabe = _sperre_status(
            letzter_lauf_dt, mindestabstand, heute
        )

        # Hochrechnung, wann die Schwelle erreicht wird: das Defizit wächst
        # täglich um ETc minus Niederschlag. Ohne Regenprognose für die
        # Folgetage ist ETc die konservative Annahme (= frühester Termin).
        prognose_tage: int | None = None
        if (
            defizit is not None
            and etc is not None
            and float(etc) > MIN_ETC_FUER_PROGNOSE
            and float(defizit) < schwelle
        ):
            prognose_tage = int(
                math.ceil((schwelle - float(defizit)) / float(etc))
            )

        if not season_active:
            entscheidung = PAUSIERT
            grund = "Saison pausiert - Equipment " + (
                "verstaut" if equipment_stored else "noch aufgebaut"
            )
        elif berechnung_fehlt:
            entscheidung = UNBEKANNT
            grund = (
                "Keine gültige Berechnung - angezeigt wird der letzte "
                "gespeicherte Stand, gegossen wird nicht"
            )
        elif zone.get("frost_skip"):
            entscheidung = AUSGESETZT
            grund = "Frost erwartet - heute wird nicht gegossen"
        elif zone.get("rain_skip"):
            entscheidung = AUSGESETZT
            grund = (
                f"Regen erwartet ({_mm(regen_prognose_mm)} mm) - heute wird "
                "nicht gegossen"
                if regen_prognose_mm is not None
                else "Regen erwartet - heute wird nicht gegossen"
            )
        elif not zone.get("min_interval_ok", True):
            entscheidung = SPERRE
            teile = []
            if tage_seit is not None:
                teile.append(f"vor {_tage_dativ(int(tage_seit))} gegossen")
            teile.append(f"Mindestabstand {_tage_nominativ(mindestabstand)}")
            if frei_ab:
                teile.append(f"frei ab {frei_ab}")
            grund = ", ".join(teile)
            grund = grund[0].upper() + grund[1:]
        elif not zone.get("min_deficit_ok", False):
            entscheidung = WARTET
            grund = f"Defizit {_mm(defizit)} von {_mm(schwelle)} mm"
            if prognose_tage:
                grund += f" - rechnerisch in {_tage_dativ(prognose_tage)} erreicht"
        else:
            entscheidung = LAEUFT
            grund = (
                f"{_mm(zone.get('duration_min'))} min für "
                f"{_mm(zone.get('gross_mm'))} mm brutto "
                f"({_mm(defizit)} mm Defizit)"
            )

        ergebnis[zone_id] = {
            "name": zone.get("name") or config.get("name"),
            "entscheidung": entscheidung,
            "grund": grund,
            "defizit_mm": defizit,
            "defizit_laufend_mm": zone.get("deficit_running"),
            "schwelle_mm": schwelle,
            "dauer_min": zone.get("duration_min"),
            "menge_mm": zone.get("gross_mm"),
            "mindestabstand_tage": mindestabstand,
            "tage_seit_bewaesserung": tage_seit,
            "frei_ab": frei_ab,
            "tage_bis_freigabe": tage_bis_freigabe,
            "prognose_tage": prognose_tage,
            "letzter_lauf": _zeitpunkt(letzter_lauf_dt),
            "letzte_menge_mm": gegossen.get("amount_mm"),
        }

    return {
        "stand": _zeitpunkt(now),
        "laeuft_anzahl": sum(
            1 for z in ergebnis.values() if z["entscheidung"] == LAEUFT
        ),
        "zonen": ergebnis,
    }
