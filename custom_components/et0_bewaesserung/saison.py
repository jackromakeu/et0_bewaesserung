"""Jahreszeitliche Prüfungen für die Equipment-Erinnerungen.

Bewusst ohne Home-Assistant-Abhängigkeiten - wie et0.py, health.py und
entscheidung.py -, damit die Logik isoliert testbar bleibt.

Hintergrund (2.2.1): Bis 2.2.0 verglich der Coordinator das heutige Datum
als Zeichenkette "MM-TT" mit dem frühesten Frühjahrsdatum:
"11-06" >= "03-01" ist wahr. Gesperrt waren damit nur Januar und Februar,
vom 1. März bis 31. Dezember galt "Frühjahr erreicht". Sobald im Herbst
verstaut war und die Vorhersage ein paar frostfreie Tage zeigte, kam die
Aufforderung zum Wiederaufbau. Das Frühjahr ist deshalb jetzt ein FENSTER
mit Anfang und Ende, und verglichen wird als (Monat, Tag), nicht als Text -
"3-1" und "03-01" sind dasselbe Datum.

Warum ein festes Fenster und kein "nächster März nach dem Verstauen": Wird
nach einem Spätfrost im April erneut verstaut, soll die Erinnerung beim
nächsten frostfreien Abschnitt im selben Frühjahr wiederkommen - nicht
erst im folgenden Jahr.
"""

from __future__ import annotations

from datetime import date, timedelta


def parse_month_day(value: object) -> tuple[int, int] | None:
    """'MM-TT' -> (Monat, Tag). Ungültige Angaben -> None.

    Der 29.02. ist zulässig (date(2000, ...) ist ein Schaltjahr), damit die
    Prüfung nicht vom laufenden Jahr abhängt.
    """
    if not isinstance(value, str):
        return None
    parts = value.strip().split("-")
    if len(parts) != 2:
        return None
    try:
        month, day = int(parts[0]), int(parts[1])
        date(2000, month, day)
    except (TypeError, ValueError):
        return None
    return month, day


def spring_window_valid(earliest: object, latest: object) -> bool:
    """Gültig nur, wenn beide Daten lesbar sind und Anfang VOR Ende liegt.

    Ein Fenster über den Jahreswechsel ist für ein Frühjahr sinnlos und wird
    abgelehnt, statt stillschweigend als "fast das ganze Jahr" zu gelten -
    genau das war der Fehler, den dieses Modul behebt.
    """
    start = parse_month_day(earliest)
    end = parse_month_day(latest)
    return start is not None and end is not None and start < end


def in_spring_window(today: date, earliest: object, latest: object) -> bool:
    """Liegt `today` im Frühjahrsfenster (Grenzen eingeschlossen)?

    Bei ungültiger Konfiguration False: Die Ausfallrichtung ist "keine
    Erinnerung". Das ist harmlos - wer im März nicht erinnert wird, baut
    trotzdem auf. Eine falsche Erinnerung im November dagegen lädt dazu
    ein, die Saison einzuschalten.
    """
    if not spring_window_valid(earliest, latest):
        return False
    start = parse_month_day(earliest)
    end = parse_month_day(latest)
    return start <= (today.month, today.day) <= end


def forecast_complete(
    forecast_dates: set[date], today: date, lookahead_days: int
) -> bool:
    """Deckt die Vorhersage JEDEN Tag von morgen bis heute+lookahead ab?

    Eine leere oder lückenhafte Vorhersage ist keine frostfreie Vorhersage.
    Bis 2.2.0 ergab ein gescheiterter Abruf eine leere Liste, und
    `any([])` ist False - die fehlende Vorhersage bekam damit das Zeugnis
    "kein Frost in Sicht". Heute wird nicht verlangt, weil manche
    Wetterdienste den laufenden Tag ab dem Nachmittag nicht mehr liefern.
    """
    needed = {today + timedelta(days=i) for i in range(1, lookahead_days + 1)}
    return needed <= forecast_dates
