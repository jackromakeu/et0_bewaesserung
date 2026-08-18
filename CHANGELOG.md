# Changelog

Alle nennenswerten Änderungen dieser Integration. Format lose angelehnt an [Keep a Changelog](https://keepachangelog.com/).

## [1.11.0]

### Added
- **Neuer Sensor `Niederschlag angerechnet`** – zeigt die Regenmenge, die tatsächlich in die Wasserbilanz des Tages eingeflossen ist (nach Wirksamkeitsfaktor). Bisher war das nur als Attribut an `ET0 Saisonsumme` versteckt. Attribute: `quelle` (im Klartext, z.B. „Radar-Messung (DWD)" oder „Wettervorhersage"), `quelle_technisch`, `rohmenge_mm` (vor Wirksamkeitsfaktor) und `regen_prognose_morgen_mm`. Erleichtert das Nachvollziehen, ob eine gemessene oder prognostizierte Menge verrechnet wurde - und mit dem Verlauf lässt sich beides über die Zeit vergleichen.

## [1.10.1]

### Fixed
- **Regen-Skip und Frost-Skip bewerteten bei manueller Neuberechnung den falschen Tag.** Beide bezogen sich auf „morgen" bzw. „den ersten Vorschautag" relativ zum **Rechenzeitpunkt** statt auf den Tag, an dem tatsächlich gegossen wird. Ein manuelles `recalculate` in den frühen Morgenstunden – also kurz vor dem Gießen – bewertete dadurch bereits den übernächsten Tag und konnte einen aktiven Skip fälschlich aufheben (oder umgekehrt einen setzen). Beide Prüfungen richten sich jetzt am **nächsten Bewässerungsmorgen** aus: vor Mittag ist das der laufende Tag, danach der Folgetag. Der reguläre Abendlauf verhält sich unverändert.

## [1.10.0]

Beide Ergänzungen adressieren dieselbe Grundfrage: Die Bilanz rechnete bisher mit idealisierten Annahmen - unbegrenzt speicherfähiger Boden, verlustfreie Ausbringung. Beides führt zu Wasserverschwendung, also genau dem, was das System verhindern soll.

### Added
- **Nutzbare Feldkapazität pro Zone** (`field_capacity_mm`, Standard 20 mm). Obergrenze für das Defizit: Mehr Wasser als das kann die Wurzelzone nicht halten, alles darüber versickert ungenutzt in die Tiefe. Ohne diesen Deckel wuchs das Defizit z.B. über eine längere Abwesenheit unbegrenzt weiter und hätte anschließend eine Bewässerungsmenge gefordert, die größtenteils verloren gegangen wäre. Richtwerte: Sand 10–15, Lehm 20–30, Ton 25–35 mm.
- **Wirkungsgrad der Ausbringung pro Zone** (`irrigation_efficiency`, Standard 0,75 für Rasen/Sprinkler und 0,85 für Tropfschlauch). Sprinkler verlieren real 20–30 % durch Windabdrift, Verdunstung und ungleiche Verteilung. Um ein Defizit von X mm tatsächlich zu decken, müssen X ÷ Wirkungsgrad ausgebracht werden. Das schließt die Inkonsistenz zum bereits vorhandenen `rain_effectiveness`, der genau dieselbe Überlegung für Regen anstellt.
- Neues Attribut `auszubringen_brutto_mm` an `Bewässerungsdauer <Zone>` – die tatsächlich auszubringende Menge inklusive Verlusten. Die Bewässerungsdauer berücksichtigt sie automatisch; dosisbasierte Systeme (z.B. Aiper) sollten sie im Skript zur Dosis-Auswahl heranziehen.

### Hinweis
Die Defaults sind bewusst konservativ gewählt – allerdings in unterschiedliche Richtungen: Bei der Feldkapazität ist ein *niedriger* Wert vorsichtig (häufiger, kleiner gießen), beim Wirkungsgrad ein *niedriger* (mehr ausbringen). Beides zusammen führt zu häufigerem, kleinerem Gießen statt seltener großer Gaben.

## [1.9.0]

### Added
- **Frostschutz während der laufenden Saison.** Die bisherige Frostlogik diente ausschließlich dem Equipment-Abbau (mehrtägige Vorwarnzeit). Neu wird zusätzlich geprüft, ob für die **unmittelbar bevorstehende Nacht** Frost erwartet wird - in dem Fall wird die Bewässerung ausgesetzt, da nasses Laub bei Frost schädlicher ist als trockenes. Sichtbar als Attribut `frost_skip_aktiv` an `Bewässerungsdauer <Zone>`; fließt in `bewaesserung_erlaubt` ein, Automationen brauchen also keine Anpassung.

### Hinweis zur begleitenden Skript-Änderung (nicht Teil des Repos)
Das Bewässerungs-Skript hat eine **Erfolgskontrolle** erhalten. Bisher wurde `reset_deficit` bedingungslos nach dem Durchlauf aufgerufen - auch wenn `wait_for_trigger` in den Timeout lief. Ein Gerät, das wegen leerem Akku, fehlendem Wasserdruck oder Funkproblem gar nicht gießt, wurde dadurch als "erledigt" verbucht: die Bilanz sprang auf 0, der Rasen blieb trocken, das Dashboard zeigte grün. Das war die einzige Stelle im System, an der ein stiller Fehler unmittelbar Pflanzenschaden verursachen konnte.

Neu wird zweistufig geprüft (läuft das Gerät überhaupt an? endet es regulär?) und nur tatsächlich ausgebrachtes Wasser verbucht - bei nur einem funktionierenden Aiper entsprechend die halbe Dosis, bei Totalausfall gar keine Buchung. Zusätzlich geht eine Warnmeldung raus.

## [1.8.0] - Fehlererkennung

Die Fehler der letzten Versionen (Datenverlust bei der Storage-Migration, fehlender Mitternachts-Rollover, blockierendes Pflichtfeld) hatten eines gemeinsam: Sie passierten **still** und fielen erst Tage später zufällig auf. Diese Version ergänzt deshalb keine neue Funktion, sondern die Fähigkeit, solche Zustände selbst zu erkennen und zu melden.

### Added
- **Neues Modul `health.py`** mit den Prüfregeln als reine, testbare Funktionen. Bewusst konservativ ausgelegt: gemeldet wird nur, was physikalisch unmöglich oder eindeutig fehlerhaft ist - Fehlalarme sind schädlicher als eine nicht gemeldete Auffälligkeit, weil sie dazu führen, dass Meldungen generell ignoriert werden.
- **Vier Prüfungen:**
  - *Ausbleibende Berechnung* – länger als 26 h kein erfolgreicher Lauf (Retry erschöpft, Timer nicht registriert, Integration hängt).
  - *Buchungslücke* – beim Rollover wurden Tage übersprungen, deren Verdunstung fehlt jetzt in der Bilanz.
  - *ET0-Plausibilität* – jahreszeitabhängige Unter- und absolute Obergrenze (12 mm/Tag). Erkennt u.a. den Fall „Berechnung lief ohne vollständigen PV-Tagesertrag" (ET0 nahe 0 im Sommer).
  - *Dauerhafter Fallback* – eine Quelle läuft seit mehreren Läufen nur noch über den zwischengespeicherten Wert, ist also faktisch tot. Ein einzelner Aussetzer löst bewusst nichts aus.
- **Neuer Sensor `Systemzustand`** (`ok`/`warnung`/`fehler`) mit den Befunden als Attribut - für den täglichen Blick aufs Dashboard.
- **Repair Issues**: Befunde erscheinen zusätzlich unter Einstellungen → Reparaturen und verschwinden automatisch, sobald das Problem behoben ist. Bewusst passiv - aktive Push-Benachrichtigungen gehören in eine selbst gesteuerte Automation, nicht in die Integration.

### Bewusst nicht umgesetzt
- Ein Backup/Restore-Mechanismus der Konfiguration wurde erwogen und verworfen: Er hätte die realen Fehler nicht verhindert (der Datenverlust fiel erst Stunden später auf, ein automatisches Backup hätte den kaputten Stand womöglich schon überschrieben). Früherkennung adressiert die Ursache statt der Symptome.

## [1.7.2]

### Fixed
- **Optionale Entity-Felder liessen sich nicht leer lassen.** `rain_sensor_entity` (neu in 1.6.0) und `weather_entity` waren zwar als `vol.Optional` deklariert, hatten aber `default=""` - ein leerer String ist für den `EntitySelector` kein gültiger Wert, wodurch das Konfigurationsformular nicht mehr gespeichert werden konnte, solange kein Sensor ausgewählt war. Beide Felder verwenden jetzt `suggested_value` statt eines Defaults: Bleibt das Feld leer, fehlt der Schlüssel schlicht im Ergebnis - das korrekte Verhalten für ein optionales Feld.

## [1.7.1]

### Fixed
- **Bewässerung hinkte seit 1.4.0 einen Tag hinterher.** Beim Datenmodell-Umbau wurde zwar die Nachhol-Prüfung des Tageswechsels implementiert (`_rollover_if_needed`), aber der eigentliche **Mitternachts-Timer fehlte**. Da die Prüfung nur innerhalb der Berechnung lief und diese nur einmal täglich (23:09) stattfindet, wanderte der Tagesbeitrag erst ~23 Stunden zu spät nach `carry`. Die Gieß-Automation am Morgen las dadurch ein um einen Tag veraltetes Defizit - im Extremfall wurde gar nicht gegossen, obwohl Bedarf bestand.
- Neuer Timer um 00:00:30, der ausschließlich umbucht und die Sensoren aktualisiert - bewusst **ohne** ET0-Neuberechnung, da der PV-Ertrag um Mitternacht auf 0 steht und eine Berechnung dort unbrauchbare Werte liefern würde. Die Gieß-Freigabe (Mindestabstand/Mindestdefizit/Dauer) wird mit dem neuen `carry` direkt neu bewertet.

## [1.7.0]

### Added
- **Neigungskorrektur der PV-Strahlung (Modulebene → Horizontale).** Bisher wurde der aus dem PV-Ertrag abgeleitete Strahlungswert direkt als horizontale Globalstrahlung verwendet. Tatsächlich messen PV-Module aber die Einstrahlung auf die *geneigte* Modulebene, während FAO-56 die *horizontale* Fläche braucht - das war die größte systematische Fehlerquelle der Näherung (Überschätzung von ET0, im Winter/Übergang besonders deutlich).
  - Verfahren: Rb-Geometriefaktor nach Liu & Jordan (Tageswerte), Diffusanteil nach Erbs-Korrelation aus dem Clearness-Index, isotropes Himmelsmodell für Diffus- und Bodenreflexion. Da der Diffusanteil vom gesuchten Horizontalwert abhängt, wird iterativ gelöst.
  - Neue Konfigurationsfelder: **PV-Dachneigung** (Grad, Standard 35, `0` deaktiviert die Korrektur) und **PV-Ausrichtung** (0 = Süd, −90 = Ost, +90 = West).
  - Neue Diagnose-Attribute an `ET0 Tagesreferenz`: `rs_modulebene_mj_m2` (Rohwert vor Korrektur) und `neigungskorrektur_faktor`.
  - Größenordnung bei 35° Süd: Faktor ~1,02 im Hochsommer, ~1,13 im Frühjahr, ~1,17 im Herbst - bei Bewölkung unter 1, da dann der Diffusanteil dominiert und eine geneigte Fläche weniger Himmel sieht.

### Bekannte Grenzen
- Der Ansatz behandelt nur eine einzelne Modulfläche mit einheitlicher Neigung/Ausrichtung. Bei Ost-West-Anlagen oder mehreren unterschiedlich ausgerichteten Teilflächen ist die Korrektur nicht anwendbar (Feld auf `0` setzen).
- Der verbleibende Fehler der PV-Näherung (Performance Ratio als fester Sammelwert, Temperaturabhängigkeit des Modulwirkungsgrads, Verschmutzung) bleibt bestehen.

## [1.6.1]

### Fixed
- **Datenverlust beim Update von 1.4.0 auf 1.5.0/1.6.0**: In 1.5.0 wurde der Storage-Schlüssel `carry_deficit` zu `season_et0_carry` umbenannt - inklusive der Format-Erkennung beim Laden. Ein von 1.4.0 geschriebener Speicher wurde dadurch fälschlich als "ganz altes Format" eingestuft, worauf die Migration nach dem Schlüssel `zone_deficits` suchte, den 1.4.0 gar nicht mehr schrieb (dort: `zone_carry`). Ergebnis: **alle Zonen-Defizite wurden beim Update auf 0 zurückgesetzt.** Die Format-Erkennung berücksichtigt jetzt alle drei Storage-Generationen.

## [1.6.0]

### Fixed
- **Niederschlagsabzug war tageszeitabhängig zufällig und konzeptionell falsch.** Bisher wurde das `precipitation`-Attribut der weather-Entity gelesen - das ist aber ein Momentan-/Prognosewert des aktuellen Vorhersageintervalls, kein Tagesniederschlag. Ein Gewitter um 15 Uhr war beim Abendlauf um 23 Uhr längst nicht mehr sichtbar und fehlte damit vollständig in der Bilanz. Jetzt wird die **Tagessumme** über `weather.get_forecasts` ermittelt (dieselbe Mechanik wie beim Regen-Skip).

### Added
- **Optionaler Sensor für gemessenen Tagesniederschlag** (`rain_sensor_entity`): Ist er konfiguriert (z.B. von einer eigenen Wetterstation), hat er Vorrang vor der Vorhersage - gemessen schlägt prognostiziert. Fällt er aus, wird automatisch auf die Prognose zurückgegriffen. Behandelt wird er als Tageszähler (`daily_reset=True`), d.h. kein Fallback über Mitternacht hinweg.
- **Regen-Wirksamkeitsfaktor** (`rain_effectiveness`, Standard 1.0): Nicht jeder mm Regen erreicht die Wurzelzone - bei Starkregen fließt ein Teil oberflächlich ab. 1.0 rechnet Regen voll an (spart Wasser, gießt seltener), 0.7-0.8 ist die konservative Einstellung (gießt häufiger).
- Neue Diagnose-Attribute an `ET0 Saisonsumme`: `niederschlag_angerechnet_mm`, `niederschlag_roh_mm` und `niederschlag_quelle` (gemessen/prognose/keine) - macht auf einen Blick nachvollziehbar, woher der Regenwert kam.

## [1.5.0]

### Changed
- **`Bewässerungsdefizit` (global) → `ET0 Saisonsumme`**: Der globale Sensor war ein Überbleibsel aus der Zeit vor den Zonen. Er wurde von nichts mehr verwendet, aber auch von nichts mehr zurückgesetzt (Bewässerung reduziert nur die Zonen-Bilanzen) - und wuchs dadurch als vermeintliche "Bilanz" unbegrenzt an. Er zeigt jetzt ehrlich das, was er tatsächlich ist: die **kumulierte ET0-Verdunstung seit Saisonstart**. Kein Niederschlagsabzug, keine Bewässerungsverrechnung, Reset nur beim Saisonwechsel. `state_class` entsprechend auf `total` geändert.
- Für die Gieß-Entscheidung sind unverändert ausschließlich die zonenspezifischen Sensoren maßgeblich - an den Automationen ändert sich nichts.

### Migration
- Der bisherige globale Wert war eine (nie zurückgesetzte) Bilanz und lässt sich nicht sinnvoll in eine ET0-Summe umrechnen → die Saisonsumme startet einmalig sauber bei 0. Die Zonen-Defizite bleiben unverändert erhalten.
- **Hinweis:** Die Entity-ID bleibt aus Kompatibilitätsgründen unverändert (`..._bewasserungsdefizit`), nur der Anzeigename ändert sich. Wer die ID angleichen möchte, kann sie einmalig manuell über Einstellungen → Entitäten umbenennen.

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
