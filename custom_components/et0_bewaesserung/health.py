"""Gesundheitsprüfungen der ET0-Bewässerungsintegration.

Bewusst als reine Funktionen ohne Home-Assistant-Abhängigkeiten gehalten,
damit die Schwellen und Regeln isoliert getestet werden können.

Designprinzip: KONSERVATIV prüfen. Gemeldet wird nur, was physikalisch
unmöglich oder eindeutig fehlerhaft ist - nicht, was ungewöhnlich aussieht.
Fehlalarme sind schädlicher als eine nicht gemeldete Auffälligkeit, weil
sie dazu führen, dass Meldungen generell ignoriert werden.
"""

from __future__ import annotations

import math
from datetime import date, datetime, timedelta

# Schweregrade
OK = "ok"
WARNUNG = "warnung"
FEHLER = "fehler"

_SEVERITY_ORDER = {OK: 0, WARNUNG: 1, FEHLER: 2}

# --- Schwellen ---
# Ein Tageslauf darf ausbleiben (Retry, Neustart); erst danach ist es ein Fehler.
MAX_HOURS_WITHOUT_CALC = 26
# Wie viele Tage in Folge darf eine Quelle nur über den Fallback laufen?
MAX_FALLBACK_STREAK = 3
# Physikalische ET0-Obergrenze für Mitteleuropa (mm/Tag). Werte darüber
# bedeuten praktisch immer kaputte Eingangsdaten, nicht echtes Wetter.
ET0_ABSOLUTE_MAX = 12.0


def _et0_min_plausible(calc_date: date) -> float:
    """Untere Plausibilitätsgrenze für ET0 (mm/Tag), jahreszeitabhängig.

    Auch bei Dauerregen im Hochsommer verdunstet noch etwas - exakt 0.0
    an einem Sommertag bedeutet fast immer, dass die Strahlung fehlte
    (z.B. Berechnung mitten in der Nacht mit PV-Ertrag = 0).
    Im Winter ist ein Wert nahe 0 dagegen völlig normal.
    """
    doy = calc_date.timetuple().tm_yday
    # Sinuskurve mit Maximum Ende Juni
    seasonal = math.sin((doy - 80) / 365 * 2 * math.pi)
    if seasonal <= 0:
        return 0.0  # Winterhalbjahr: keine sinnvolle Untergrenze
    return round(0.4 * seasonal, 2)


def evaluate_health(
    *,
    now: datetime,
    last_success: datetime | None,
    current_day: str | None,
    day_gap: int,
    et0: float | None,
    calc_date: date,
    fallback_streaks: dict[str, int],
    season_active: bool,
) -> dict:
    """Bewertet den Systemzustand und liefert Status plus Befundliste.

    Rückgabe:
        {"status": ok|warnung|fehler, "issues": [{code, severity, message}, ...]}
    """
    issues: list[dict] = []

    # --- 1. Ausbleibende Berechnung ---
    if last_success is None:
        issues.append(
            {
                "code": "no_calculation_yet",
                "severity": WARNUNG,
                "message": "Es wurde noch keine erfolgreiche Berechnung durchgeführt.",
            }
        )
    else:
        hours = (now - last_success).total_seconds() / 3600
        if hours > MAX_HOURS_WITHOUT_CALC:
            issues.append(
                {
                    "code": "calculation_overdue",
                    "severity": FEHLER,
                    "message": (
                        f"Seit {hours:.0f} Stunden keine erfolgreiche Berechnung "
                        f"(erwartet: täglich). Die Bewässerung arbeitet mit "
                        f"veralteten Werten."
                    ),
                }
            )

    # --- 2. Lücke in der Buchungskette ---
    # day_gap = übersprungene Tage beim letzten Rollover. 1 = normal.
    if day_gap > 1:
        issues.append(
            {
                "code": "day_gap",
                "severity": FEHLER if day_gap > 2 else WARNUNG,
                "message": (
                    f"{day_gap - 1} Tag(e) ohne Buchung übersprungen - die "
                    f"Verdunstung dieser Tage fehlt in der Bilanz."
                ),
            }
        )

    # --- 3. Plausibilität des ET0-Ergebnisses ---
    if et0 is not None and season_active:
        if et0 > ET0_ABSOLUTE_MAX:
            issues.append(
                {
                    "code": "et0_implausible_high",
                    "severity": FEHLER,
                    "message": (
                        f"ET0 von {et0} mm/Tag liegt über dem physikalisch "
                        f"Möglichen ({ET0_ABSOLUTE_MAX} mm) - Eingangsdaten prüfen."
                    ),
                }
            )
        else:
            min_plausible = _et0_min_plausible(calc_date)
            if min_plausible > 0 and et0 < min_plausible:
                issues.append(
                    {
                        "code": "et0_implausible_low",
                        "severity": WARNUNG,
                        "message": (
                            f"ET0 von {et0} mm/Tag ist für die Jahreszeit "
                            f"unplausibel niedrig (erwartet mindestens "
                            f"{min_plausible} mm). Häufigste Ursache: Berechnung "
                            f"lief zu einem Zeitpunkt ohne vollständigen "
                            f"PV-Tagesertrag."
                        ),
                    }
                )

    # --- 4. Dauerhafter Fallback-Betrieb ---
    for entity_id, streak in sorted(fallback_streaks.items()):
        if streak >= MAX_FALLBACK_STREAK:
            issues.append(
                {
                    "code": "persistent_fallback",
                    "severity": FEHLER,
                    "message": (
                        f"{entity_id} liefert seit {streak} Läufen keine eigenen "
                        f"Werte mehr - es wird durchgehend der zwischengespeicherte "
                        f"Wert verwendet."
                    ),
                }
            )

    status = OK
    for issue in issues:
        if _SEVERITY_ORDER[issue["severity"]] > _SEVERITY_ORDER[status]:
            status = issue["severity"]

    return {"status": status, "issues": issues}
