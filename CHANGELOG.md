# Changelog

Alle nennenswerten Änderungen dieser Integration. Format lose angelehnt an [Keep a Changelog](https://keepachangelog.com/).

## [1.4.0] - Datenmodell-Umbau: Tages-Sperre entfällt

Die bisherige Buchungslogik war **additiv** (`defizit += ETc`). Weil man bei einer Addition zwangsläufig verhindern muss, dass zweimal addiert wird, brauchte es eine "Tages-Sperre" - und die hat eine ganze Reihe von Folgeproblemen erzeugt (blockierte Korrekturen, verfälschte Werte durch Testläufe zur falschen Zeit, ein `force`-Flag als Krücke für die Krücke). Diese Version ersetzt das Fundament durch ein Modell, in dem die Berechnung **idempotent** ist.

### Changed
- **Neues Datenmodell `carry` + `today`**:
  - `carry` = aufgelaufenes Defizit **abgeschlossener** Tage, abzüglich Bewässerung → die Basis für die Gieß-Entscheidung.
  - `today` = ETc − Niederschlag des **laufenden** Tages → wird bei jeder Berechnung **überschrieben**, nie addiert.
  - Beim Tageswechsel wandert `today` per Rollover in `carry`.
- **Die Tages-Sperre entfällt ersatzlos.** Mehrfaches `recalculate` am selben Tag ist jetzt folgenlos, weil Überschreiben idempotent ist. Ein Testlauf zu einem ungünstigen Zeitpunkt (z.B. kurz nach Mitternacht mit PV-Ertrag=0) verfälscht die Bilanz nicht mehr dauerhaft - der reguläre Abendlauf überschreibt ihn einfach.
- **Rollover mit Nachhol-Prüfung** statt reinem Mitternachts-Timer: Der Tageswechsel wird bei jeder Berechnung geprüft und nachgeholt, falls er verpasst wurde (HA-Neustart, Update, Stromausfall um Mitternacht).
- Automatische **Migration** des bestehenden gespeicherten Zustands beim ersten Start (bereits gebuchter heutiger Beitrag wird korrekt herausgerechnet).

### Added
- Neuer Sensor **`Defizit laufend <Zone>`**: abgeschlossene Tage + laufender Tag. Bewegt sich im Tagesverlauf, im Gegensatz zum Gieß-Defizit, das nach dem morgendlichen Gießen bis zum Abend auf 0 steht (löst nebenbei das "toter Tacho"-Problem im Dashboard).
- Neue Attribute: `defizit_laufend_mm`, `laufender_tag`, `heutiger_beitrag_mm` an den jeweiligen Sensoren.

### Removed
- **`force`-Parameter des `recalculate`-Services** (eingeführt in 1.3.0) - durch die idempotente Berechnung ersatzlos überflüssig geworden.

## [1.3.1]

### Added
- **Diagnose-Transparenz für den Buchungs-Zustand**: `heute_bereits_gebucht` (= internes `last_processed_date`) und `heutiger_beitrag_mm`/`heutiger_beitrag_referenz_mm` sind jetzt als Attribute an `ET0 Tagesreferenz` (global) und `Bewässerungsdefizit <Zone>` (pro Zone) sichtbar. Bisher musste dieser interne Zustand mühsam aus Verlaufsgraphen rekonstruiert werden, was wiederholt zu falschen Annahmen bei der Fehlersuche geführt hat - jetzt direkt einsehbar.

## [1.3.0]

### Added
- **`recalculate`-Service um Feld `force` erweitert**: Löst gezielt die Tages-Sperre, indem die HEUTIGE (bereits erfolgte) Buchung rückgängig gemacht wird, bevor neu berechnet wird - ohne die Bilanz vorheriger Tage zu beeinflussen. Behebt eine echte Lücke: bisher gab es keinen Weg, eine fehlerhafte Buchung desselben Tages (z.B. ein Testlauf kurz nach Mitternacht mit PV-Ertrag=0, der eine viel zu niedrige ET0/ETc einbucht) zu korrigieren, außer bis zum nächsten Kalendertag zu warten oder einen globalen Reset zu machen (der auch andere Zonen/Tage mit zurücksetzt).
- Neue interne Coordinator-Methode `async_force_recalculate()` sowie das Tracking `_today_contribution`/`_today_contribution_global`, das sich merkt, wie viel eine Buchung tatsächlich zur Bilanz beigetragen hat (nicht nur ob gebucht wurde).

## [1.2.2]

### Fixed
- **Zonen-Reset mit `amount_mm` setzte das Defizit bisher hart auf 0**, statt die tatsächlich abgegebene Menge abzuziehen. Bei dosisbasierten Systemen mit nur diskreten Mengenstufen (z.B. Aiper: 3/6/13mm) führte das dazu, dass bei "nächstgelegener Dosis" ein Rest-Defizit fälschlich verschwand (z.B. 4,2mm Bedarf, 3mm geliefert → Bilanz zeigte 0 statt korrekt 1,2mm) bzw. bei Überdosierung ein Guthaben nicht erfasst wurde. `async_reset_deficit` zieht `amount_mm` jetzt vom aktuellen Defizit ab (Untergrenze -10mm, analog zur täglichen Fortschreibung) statt es zu überschreiben. Ohne `amount_mm`-Angabe bleibt das alte Verhalten (hart auf 0) für Abwärtskompatibilität erhalten.

## [1.2.1]

### Fixed
- Zonen-Namensvergleich in `reset_deficit` schlug fehl, obwohl der übergebene Name optisch exakt mit dem konfigurierten Zonennamen übereinstimmte ("Zone 'Sträucher' nicht gefunden"). Ursache: unterschiedliche Unicode-Normalisierung von Umlauten (NFC vs. NFD) je nach Eingabequelle (Config-UI vs. YAML-Editor). Der Vergleich normalisiert beide Seiten jetzt vor dem Abgleich (`unicodedata.normalize("NFC", ...)`, zusätzlich mit `.strip()`).

## [1.2.0]

### Added
- **Mindestdefizit pro Zone** (`min_deficit_mm`, Standard 1,5 mm). Verhindert Bewässerung bei nur geringfügigem Wasserbedarf. Konfigurierbar im Zonen-Schritt (0–20 mm).
- **Kombiniertes `bewaesserung_erlaubt`-Attribut** an `Bewässerungsdauer <Zone>`: fasst Regen-Skip, Mindestabstand und Mindestdefizit zu einem einzigen Flag zusammen - Automationen müssen jetzt nur noch eine statt drei Bedingungen prüfen.
- **Neue Binary-Sensor-Entitäten für die Fehlersuche** - machen die einzelnen Bausteine der Gieß-Entscheidung direkt auf dem Dashboard sichtbar, statt nur als Attribut verborgen zu sein:
  - `Mindestabstand erfüllt <Zone>` (pro Zone)
  - `Mindestdefizit erfüllt <Zone>` (pro Zone)
  - `Regen erwartet (Skip aktiv)` (global, inkl. Attribut mit der vorhergesagten Regenmenge)

### Changed
- `Bewässerungsdauer <Zone>` wird jetzt zusätzlich auf 0 gesetzt, wenn das konfigurierte Mindestdefizit noch nicht erreicht ist (bisher nur Regen-Skip und Mindestabstand).

## [1.1.0]

### Added
- **Mindestabstand zwischen Bewässerungen pro Zone** (`min_days`, Standard 1 Tag = bisheriges Verhalten unverändert). Verhindert zu häufiges, oberflächliches Gießen zugunsten selteneren, dafür tieferen Gießens (fördert Wurzelwachstum). Konfigurierbar im Zonen-Schritt des Einrichtungs-/Konfigurieren-Dialogs (1–14 Tage).
- Neue Attribute an `Bewässerungsdauer <Zone>`: `mindestabstand_erfuellt` (bool) und `tage_seit_letzter_bewaesserung`.
- Neue interne Coordinator-Methode `_min_interval_status()` zur Berechnung des Tagesabstands seit der letzten dokumentierten Bewässerung dieser Zone (basiert auf dem bereits vorhandenen "Zuletzt bewässert"-Zeitstempel).

### Changed
- `Bewässerungsdauer <Zone>` wird jetzt zusätzlich zum Regen-Skip auch dann auf 0 gesetzt, wenn der konfigurierte Mindestabstand seit der letzten Bewässerung noch nicht erreicht ist.

## [1.0.1]

### Fixed
- `after_dependencies: ["met"]` im Manifest ergänzt: verhindert eine mögliche Race Condition beim HA-Start, bei der die Wetter-Vorhersage-Abfrage (Regen-Skip, Frost-Erkennung) fehlschlägt, weil die met.no-Integration ihre Entity zum Zeitpunkt unseres ersten Laufs noch nicht bereitgestellt hat ("Service call requested response data but did not match any entities").

## [1.0.0] - Erster dokumentierter Stand

Die Integration ist iterativ aus einer einfachen YAML-Paket-Lösung heraus zu einer vollständigen Custom Component gewachsen. Diese erste Version fasst die gesamte bisherige Entwicklung zusammen.

### Added – Kernfunktion
- FAO-56 Penman-Monteith ET0-Berechnung (`et0.py`), Solarstrahlung näherungsweise aus dem PV-Tagesertrag abgeleitet statt über einen dedizierten Pyranometer-Sensor
- `DataUpdateCoordinator`-basierte Architektur mit persistenter Speicherung (`homeassistant.helpers.storage.Store`)
- Config Flow (2 Schritte: Allgemein + Zonen) mit Eingabe-Validierung der gewählten Entities vor dem Speichern
- Options Flow zur nachträglichen Anpassung aller Einstellungen

### Added – Zonen & Bewässerungslogik
- Bis zu 3 konfigurierbare Zonen mit individuellem Kc-Faktor und Tropfrate
- Pro-Zone-Sensoren: ETc, Bewässerungsdefizit, Bewässerungsdauer, Zuletzt bewässert (inkl. abgegebener Menge)
- Tages-Sperre: Bilanz wird pro Kalendertag nur einmal fortgeschrieben, unabhängig davon wie oft neu berechnet/neu gestartet wird
- Vorausschauender Regen-Skip über `weather.get_forecasts` (setzt `Bewässerungsdauer` bei erwarteten Niederschlag auf 0, ohne die Bilanz selbst zu beeinflussen)

### Added – Saison- & Frostmanagement
- `switch.gartensaison_aktiv` zum manuellen Pausieren der kompletten Logik (setzt bei jedem Umschalten die Bilanz zurück)
- Frost-Erkennung über die Tiefsttemperatur-Vorhersage (`binary_sensor.frost_erwartet...`, "sticky" bis Equipment-Abbau bestätigt)
- Frühjahrs-Erkennung anhand Kalenderdatum + fehlender Frost-Vorhersage (`binary_sensor.fruehjahr_bereit...`)
- Service `equipment_status_setzen`: verkettet die Bestätigung "Equipment verstaut/aufgebaut" automatisch mit dem Saison-Schalter

### Added – Ausfallsicherheit & Diagnose
- Retry-Mechanismus für den geplanten Tageslauf (bis zu 3 Versuche im 10-Minuten-Abstand)
- Fallback auf den letzten bekannten Wert bei kurzzeitig nicht verfügbaren Quellen (max. 26h)
- Tages-Zähler-Sonderfall (`daily_reset`): Fallback für den PV-Ertragssensor wird bewusst NICHT über eine Mitternachtsgrenze hinweg verwendet
- Ausführliche Diagnose-Logs (exakter Entity-Zustand, `last_exception` direkt in Retry-Meldungen, Momentaufnahme aller Eingangswerte)
- Temporärer `DIAGNOSE_MODE`-Schalter für stündliche statt tägliche Läufe während der Fehlersuche

### Fixed
- `NumberSelector`-Konfiguration mit `step < 0.001` führte zu einem stillen, unprotokollierten 400-Fehler beim Öffnen des Einrichtungsdialogs (HA-interne Validierungsregel)
- `OptionsFlow.__init__` mit manueller `self.config_entry`-Zuweisung crashte in aktuellen HA-Versionen (`config_entry` ist eine reine Property der Basisklasse)
- Zeit-Parsing (`update_time`) akzeptiert jetzt sowohl `HH:MM` als auch `HH:MM:SS` (ein Zeit-Picker ohne Sekunden lieferte nur 2 statt 3 Teile)
- Mehrfachzählung der Tagesbilanz bei wiederholten manuellen Neuberechnungen/Neustarts am selben Tag behoben (Tages-Sperre)
- `reset_deficit` löscht bei einem globalen Reset jetzt auch die Tages-Sperre selbst, damit direkt danach korrekt neu gebucht werden kann

### Known Issues / TODO
- Solarstrahlungs-Näherung berücksichtigt keine Dachneigung/-ausrichtung – für Bewässerungszwecke ausreichend, nicht wissenschaftlich exakt
- Performance Ratio muss einmalig gegen echte Referenzdaten kalibriert werden
- Tropfraten müssen pro Anlage manuell ermittelt werden
- `DIAGNOSE_MODE` steht in dieser Version auf `False` (Normalbetrieb) – während der PV-Sensor-Fehlersuche zeitweise auf `True`
