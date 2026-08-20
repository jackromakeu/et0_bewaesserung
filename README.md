# ET0 Bewässerung

Lokale Home-Assistant-Integration für evapotranspirationsbasierte Gartenbewässerung nach **FAO-56 Penman-Monteith** – ohne Bodenfeuchtesensoren. Die benötigte Solarstrahlung wird näherungsweise aus dem Ertrag einer vorhandenen PV-Anlage abgeleitet, statt einen eigenen Pyranometer zu erfordern.

## Inhaltsverzeichnis

- [Funktionsprinzip](#funktionsprinzip)
- [Datenmodell](#datenmodell)
- [Zwei vollständig durchgerechnete Beispiele](#zwei-vollständig-durchgerechnete-beispiele)
- [Voraussetzungen](#voraussetzungen)
- [Installation](#installation)
- [Konfiguration](#konfiguration)
- [Entitäten](#entitäten)
- [Services](#services)
- [Zonen: Kc, Tropfrate, Feldkapazität, Wirkungsgrad](#zonen-kc-tropfrate-feldkapazität-wirkungsgrad)
- [Regen: Skip und Anrechnung](#regen-skip-und-anrechnung)
- [PV-Näherung und Neigungskorrektur](#pv-näherung-und-neigungskorrektur)
- [Frost- und Saisonmanagement](#frost--und-saisonmanagement)
- [Ausfallsicherheit und Fehlererkennung](#ausfallsicherheit-und-fehlererkennung)
- [Genauigkeit und Grenzen](#genauigkeit-und-grenzen)
- [Automationen](#automationen)

## Funktionsprinzip

1. **ET0-Berechnung** einmal täglich (abends, wenn der PV-Tagesertrag vollständig ist) nach FAO-56 Penman-Monteith aus Tages-Min/Max-Temperatur, mittlerer Luftfeuchte, mittlerem Wind und der aus dem PV-Ertrag abgeleiteten, neigungskorrigierten Solarstrahlung.
2. **Pro Zone** wird ETc = ET0 × Kc berechnet, abzüglich angerechnetem Niederschlag.
3. **Beim Tageswechsel** wandert der Tagesbeitrag in das Defizit der abgeschlossenen Tage, gedeckelt auf die Feldkapazität – das ist die Basis für die Bewässerung.
4. **Nach dem Gießen** meldet eine Automation die tatsächlich in der Wurzelzone angekommene Menge zurück; sie wird vom Defizit abgezogen.

## Datenmodell

Zentral für das Verständnis – seit v1.4.0:

| Größe | Bedeutung |
|---|---|
| **carry** | Defizit **abgeschlossener** Tage, abzüglich Bewässerung, gedeckelt auf die Feldkapazität. Basis für die Gieß-Entscheidung. Sichtbar als `Bewässerungsdefizit <Zone>`. |
| **today** | ETc − angerechneter Niederschlag des **laufenden** Tages. Wird bei jeder Berechnung **überschrieben**, nie addiert. |
| **Rollover** | Um 00:00:30 wandert `today` nach `carry`. Zusätzlich wird bei jeder Berechnung geprüft, ob ein Tageswechsel verpasst wurde (HA-Neustart o.ä.) und ggf. nachgeholt. |

Weil `today` überschrieben statt addiert wird, ist die Berechnung **idempotent**: Sie kann beliebig oft am selben Tag laufen (auch manuell über die Button-Entität), ohne die Bilanz zu verfälschen. Eine „Tages-Sperre" wie in frühen Versionen ist dadurch überflüssig.

**Dasselbe Prinzip gilt seit v1.12.0 auch für Regen- und Frost-Skip**: `heute` ist der beim Rollover fixierte, für den ganzen Tag stabile Wert (Automationen fragen nur diesen ab – unabhängig davon, ob morgens oder abends gegossen wird), `morgen` wird laufend neu ermittelt und übernimmt beim nächsten Tageswechsel die Rolle von `heute`.

**Restmengen gehen nicht verloren:** Beim Zurückmelden einer Bewässerung wird die tatsächlich angekommene Menge abgezogen, nicht das ganze Defizit gelöscht. Wer bei 6 mm Bedarf nur 4,5 mm netto abgibt, behält 1,5 mm im Defizit – am nächsten Tag wird darauf aufgebaut.

## Zwei vollständig durchgerechnete Beispiele

Beide Beispiele sind mit dem tatsächlichen Rechenkern nachvollzogen (`et0.py`), keine Wunschzahlen. Gedacht als Referenz, um die Logik auch nach einer längeren Winterpause wieder einordnen zu können.

### Beispiel 1: Normaler Sommertag, kein Regen, Rasen-Zone (Aiper)

**Zeitpunkt: 23:09 Uhr, planmäßige Berechnung.**

| Sensor (Konfigurationsfeld) | Wert |
|---|---|
| `temp_max_entity` | 28 °C |
| `temp_min_entity` | 16 °C |
| `humidity_mean_entity` | 55 % |
| `wind_mean_entity` | 12 km/h |
| `pv_yield_entity` (Tagesertrag) | 24 kWh |
| `pv_tilt` / `pv_azimuth` | 35° / −5° |
| `kwp` / `performance_ratio` | 5,1 kWp / 0,80 |

**Schritt 1 – Solarstrahlung ableiten** (`Solarstrahlung (PV-Proxy)`):
```
Rs (Modulebene) = PV-Ertrag / (kWp × PR) × 3,6 = 24 / (5,1 × 0,80) × 3,6 = 21,18 MJ/m²
Neigungskorrektur-Faktor (Sommer, 35°) = 0,945
Rs (horizontal) = 21,18 / 0,945 = 22,41 MJ/m²
```

**Schritt 2 – ET0** (`ET0 Tagesreferenz`), FAO-56 Penman-Monteith mit obigen Werten:
```
ET0 = 5,32 mm
```

**Schritt 3 – ETc der Zone** (`ETc Rasen`), Kc = 0,80:
```
ETc = ET0 × Kc = 5,32 × 0,80 = 4,26 mm
```

**Schritt 4 – Niederschlag**: keiner gefallen/vorhergesagt → 0 mm.
```
today (Rasen) = ETc − Regen = 4,26 − 0 = 4,26 mm
```

**Schritt 5 – 00:00:30 Uhr, Rollover.** Angenommen, `Bewässerungsdefizit Rasen` (carry) stand vorher bei 3,5 mm:
```
carry_neu = carry_alt + today = 3,5 + 4,26 = 7,76 mm
```
→ `Bewässerungsdefizit Rasen` zeigt ab jetzt **7,76 mm**, bis zur nächsten Bewässerung.

**Schritt 6 – Gieß-Automation liest den Wert** (z. B. 05:00 Uhr), Wirkungsgrad 0,75, Tropfrate 0,25 mm/min:
```
brutto = carry / Wirkungsgrad = 7,76 / 0,75 = 10,35 mm
Dauer = brutto / Tropfrate = 10,35 / 0,25 = 41,4 min
```
Nach dem Gießen ruft die Automation `reset_deficit` mit der **netto** angekommenen Menge auf (hier: 7,76 mm, da voll ausgebracht) → `carry` fällt auf 0.

### Beispiel 2: Bewölkter Tag mit gemessenem Regen, Sträucher-Zone (Tropfschlauch)

**Zeitpunkt: 23:09 Uhr.**

| Sensor | Wert |
|---|---|
| `temp_max_entity` / `temp_min_entity` | 19 °C / 13 °C |
| `humidity_mean_entity` | 78 % |
| `wind_mean_entity` | 18 km/h |
| `pv_yield_entity` | 8 kWh (bewölkter Tag) |
| `rain_sensor_entity` (DWD „Precipitation last 24 hours") | 6,0 mm |

**Schritt 1–2 – Strahlung und ET0:**
```
Rs (horizontal) = 7,6 MJ/m²  (Neigungsfaktor 0,928 - bei Bewölkung <1, da Diffusanteil dominiert)
ET0 = 2,23 mm
```

**Schritt 3 – ETc**, Zone Sträucher mit Kc = 0,50:
```
ETc = 2,23 × 0,50 = 1,11 mm
```

**Schritt 4 – Niederschlag, gemessen statt prognostiziert** (der DWD-Sensor hat Vorrang vor der Wettervorhersage):
```
Wirksamkeitsfaktor = 0,85 (Tropfschlauch/Boden - nicht jeder mm versickert nutzbar)
angerechnet = 6,0 × 0,85 = 5,1 mm

today = ETc − angerechneter Regen = 1,11 − 5,1 = −3,99 mm   (negativ!)
```

**Schritt 5 – Rollover.** Angenommen carry vorher (nach vorangegangener Trockenphase) = 16,0 mm:
```
carry_neu (ungedeckelt) = 16,0 + (−3,99) = 12,01 mm
Feldkapazität = 20 mm → keine Deckelung nötig, da 12,01 < 20
```
→ Der Regen hat das Defizit spürbar reduziert, aber nicht auf 0 gebracht.

**Zusatz – wann die Feldkapazität tatsächlich greift:** Wäre carry vorher z. B. 18,5 mm gewesen und der Tag *trocken* mit today = +4,26 mm:
```
ungedeckelt = 18,5 + 4,26 = 22,76 mm
gedeckelt auf Feldkapazität 20 mm → carry_neu = 20,0 mm
```
Die überschüssigen 2,76 mm gehen bewusst „verloren" – mehr Wasser, als der Boden speichern kann, würde beim Gießen ohnehin unterhalb der Wurzeln versickern.

## Voraussetzungen

- Home Assistant mit aktivem `recorder`
- Eine `weather.*`-Entity mit Unterstützung für `weather.get_forecasts` (Regen-Skip, Frost-Vorschau, Niederschlags-Prognose als Fallback)
- Sensoren für: Tages-Maximaltemperatur, Tages-Minimaltemperatur, mittlere Luftfeuchte, mittlere Windgeschwindigkeit (km/h), PV-Tagesertrag (kWh, **täglich auf 0 zurückgesetzter Zähler**, kein Lifetime-Zähler)
- PV-Anlage mit bekannter Nennleistung
- Optional: ein Sensor mit **gemessenem** Tagesniederschlag (z. B. `ha-dwd-precipitation`, Entity „Precipitation last 24 hours") – hat Vorrang vor der Prognose

## Installation

**Über HACS:** HACS → „⋮" → Benutzerdefinierte Repositories → URL eintragen, Kategorie „Integration" → installieren → Home Assistant neu starten.

**Manuell:** Ordner `custom_components/et0_bewaesserung` nach `/config/custom_components/` kopieren, Home Assistant **vollständig** neu starten.

Die Integration bringt ein eigenes Icon/Logo mit (`brand/`-Ordner, seit v1.11.1, benötigt HA 2026.3+).

## Konfiguration

Einstellungen → Geräte & Dienste → „Integration hinzufügen" → „ET0 Bewässerung". Zwei Schritte, später jederzeit über „Konfigurieren" änderbar.

**Schritt 1 – Allgemein**

| Feld | Beschreibung |
|---|---|
| `temp_max_entity` / `temp_min_entity` | Tages-Höchst-/Tiefsttemperatur |
| `humidity_mean_entity` | mittlere Luftfeuchte |
| `wind_mean_entity` | mittlere Windgeschwindigkeit (km/h) |
| `pv_yield_entity` | PV-Tagesertrag (kWh, täglicher Zähler) |
| `weather_entity` | Wetter-Entity für Niederschlag/Frost (optional) |
| `latitude` / `elevation` | Standort (aus HA vorbefüllt) |
| `kwp` / `performance_ratio` | PV-Nennleistung und Performance Ratio |
| `pv_tilt` / `pv_azimuth` | Dachneigung (Grad) und Ausrichtung (0 = Süd) |
| `update_time` | Uhrzeit der täglichen Berechnung (`HH:MM` oder `HH:MM:SS`) |
| `rain_skip_enabled` / `rain_skip_threshold_mm` | vorausschauender Regen-Skip |
| `rain_sensor_entity` | gemessener Tagesniederschlag (optional, hat Vorrang vor Prognose) |
| `rain_effectiveness` | Anteil des Regens, der die Wurzelzone erreicht |
| `frost_lookahead_days` / `frost_threshold_c` | Frost-Vorwarnung (Equipment-Abbau) |
| `spring_earliest_date` | frühestes Frühjahrsdatum (`MM-TT`) |

**Schritt 2 – Zonen** (bis zu 3, Name leer = deaktiviert): `name`, `kc`, `drip_rate`, `min_days`, `min_deficit_mm`, `field_capacity_mm`, `irrigation_efficiency`.

## Entitäten

Alle Entitäten hängen an einem gemeinsamen Gerät „ET0 Bewässerung".

**Global**

| Entität | Typ | Beschreibung |
|---|---|---|
| ET0 Tagesreferenz | sensor | Tages-ET0 (mm) inkl. umfangreicher Diagnose-Attribute |
| Solarstrahlung (PV-Proxy) | sensor | Aus PV-Ertrag abgeleitete, neigungskorrigierte Globalstrahlung (MJ/m²) |
| Niederschlag angerechnet | sensor | Für heute in die Bilanz eingeflossene Regenmenge, mit Quelle im Klartext |
| ET0 Saisonsumme | sensor | Kumulierte Verdunstung seit Saisonstart (Statistik, keine Bilanz) |
| Systemzustand | sensor | `ok`/`warnung`/`fehler` - automatische Fehlererkennung, siehe unten |
| Gartensaison aktiv | switch | Aus = komplette Logik pausiert, Bilanz wird zurückgesetzt |
| Jetzt neu berechnen | button | Manuelle Neuberechnung, seit v1.4.0 jederzeit unschädlich |
| Regen erwartet (Skip aktiv heute) | binary_sensor | Regen-Skip für heute aktiv |
| Frost erwartet - Equipment-Abbau nötig | binary_sensor | „Sticky" bis Bestätigung |
| Frühjahr bereit - Equipment-Aufbau möglich | binary_sensor | „Sticky" bis Bestätigung |
| Equipment verstaut | binary_sensor | An = Winterkonfiguration |

**Pro Zone**

| Entität | Beschreibung |
|---|---|
| ETc `<Zone>` | Wasserbedarf des laufenden Tages (mm) |
| Bewässerungsdefizit `<Zone>` | **Basis für die Gieß-Entscheidung** (abgeschlossene Tage, `carry`) |
| Defizit laufend `<Zone>` | inkl. laufendem Tag (`carry + today`) – bewegt sich über den Tag |
| Bewässerungsdauer `<Zone>` | Empfohlene Gießdauer (min, bereits inkl. Wirkungsgrad); 0 wenn nicht freigegeben |
| Zuletzt bewässert `<Zone>` | Zeitstempel, Attribut `menge_mm` |
| Mindestabstand erfüllt `<Zone>` | binary_sensor, für die Fehlersuche |
| Mindestdefizit erfüllt `<Zone>` | binary_sensor, für die Fehlersuche |

**Wichtigstes Attribut:** `bewaesserung_erlaubt` an `Bewässerungsdauer <Zone>` fasst Regen-Skip, Frost-Skip, Mindestabstand und Mindestdefizit zu einem Flag zusammen – Automationen brauchen nur diese eine Bedingung.

## Services

### `et0_bewaesserung.recalculate`
Sofortige Neuberechnung. Beliebig oft wiederholbar (idempotent). Entspricht der Button-Entität „Jetzt neu berechnen".

### `et0_bewaesserung.reset_deficit`
| Feld | Beschreibung |
|---|---|
| `zone` | Zonenname. Ohne Angabe: globaler Reset aller Zonen. |
| `amount_mm` | Tatsächlich in der Wurzelzone angekommene Menge – wird vom Defizit **abgezogen** und in der Historie gespeichert. Ohne Angabe: hart auf 0. |

Der Zonen-Name wird unicode-normalisiert verglichen (Umlaute funktionieren unabhängig von der Eingabequelle).

### `et0_bewaesserung.equipment_status_setzen`
| Feld | Beschreibung |
|---|---|
| `verstaut` | `true` = verstaut (schaltet Saison automatisch aus), `false` = aufgebaut (schaltet Saison automatisch an) |

## Zonen: Kc, Tropfrate, Feldkapazität, Wirkungsgrad

**Kc (Crop Coefficient)** skaliert ET0 auf den tatsächlichen Bedarf. FAO-56-Richtwerte:

| Bepflanzung | Kc |
|---|---|
| Rasen | 0,70 – 0,85 |
| Beete / Blumen | 0,90 – 1,10 |
| Sträucher / Hecken (etabliert) | 0,40 – 0,55 |

**Tropfrate** (mm/min) muss an die eigene Anlage angepasst werden:
```
Tropfrate [mm/min] = (Durchfluss pro Tropfer [L/h] × Tropfer pro m²) / 60
```
Genauer als jede Rechnung: Eimer-Test – Leitung X Minuten laufen lassen, Menge messen, auf die Fläche umrechnen.

**`field_capacity_mm`** (Standard 20) – nutzbare Feldkapazität der Wurzelzone. Obergrenze für `carry`: mehr Wasser, als der Boden halten kann, würde beim Gießen unterhalb der Wurzeln versickern. Richtwerte: Sand 10–15, Lehm 20–30, Ton 25–35 mm.

**`irrigation_efficiency`** (Standard 0,75 Sprinkler / 0,85 Tropfschlauch) – welcher Anteil der ausgebrachten Menge kommt tatsächlich an? Sprinkler verlieren real 20–30 % durch Windabdrift und Verdunstung. Die **Bewässerungsdauer** rechnet automatisch die nötige Brutto-Menge (`carry ÷ Wirkungsgrad`); zurückgemeldet werden sollte an `reset_deficit` die **Netto**-Menge (siehe Beispiel 1 oben).

**`min_days`** – Mindestabstand zwischen zwei Bewässerungen (Standard 1). Höhere Werte fördern seltenes, dafür tieferes Gießen.

**`min_deficit_mm`** – Mindestdefizit, ab dem überhaupt gegossen wird (Standard 1,5).

## Regen: Skip und Anrechnung

Zwei getrennte Mechanismen, beide seit v1.12.0 mit fester heute/morgen-Trennung (siehe [Datenmodell](#datenmodell)):

**Regen-Skip (vorausschauend):** Liegt die Niederschlagsprognose für **heute** über `rain_skip_threshold_mm`, wird `Bewässerungsdauer` auf 0 gesetzt. Der Wert wird beim Rollover fixiert und bleibt für den ganzen Tag stabil – unabhängig davon, ob eine Zone morgens oder abends gießt.

**Anrechnung in der Bilanz:** Der Niederschlag des **heutigen** Tages wird vom Tagesbeitrag abgezogen. Quellen in dieser Reihenfolge:
1. `rain_sensor_entity` (gemessen, z. B. DWD-Radar) – hat Vorrang
2. Tagessumme aus `weather.get_forecasts`

Der Wert wird mit `rain_effectiveness` gewichtet (siehe Beispiel 2 oben). `1.0` rechnet Regen voll an (spart Wasser), `0.7–0.8` ist konservativ (gießt häufiger). Die Quelle steht im Klartext am Sensor `Niederschlag angerechnet`.

## PV-Näherung und Neigungskorrektur

PV-Module messen die Einstrahlung auf die **geneigte Modulebene**; FAO-56 benötigt die **horizontale** Fläche. Ohne Korrektur wird ET0 systematisch überschätzt.

Die Integration rechnet um über: Rb-Geometriefaktor nach Liu & Jordan (Tageswerte), Diffusanteil nach Erbs-Korrelation aus dem Clearness-Index, isotropes Himmelsmodell für Diffus- und Bodenreflexion, iterativ gelöst.

Größenordnung bei 35° Süd (Faktor = Modulebene ÷ Horizontale):

| Zeitraum | Faktor |
|---|---|
| Hochsommer | ~0,93–1,05 |
| Frühjahr / Herbst | ~1,10–1,20 |
| Bewölkt | < 1,0 (Diffusanteil dominiert, siehe Beispiel 2) |

`pv_tilt = 0` deaktiviert die Korrektur. Bei Ost-West-Anlagen oder mehreren unterschiedlich ausgerichteten Teilflächen ist sie nicht anwendbar.

## Frost- und Saisonmanagement

- **Herbst:** Sinkt die Tiefsttemperatur-Prognose innerhalb von `frost_lookahead_days` unter `frost_threshold_c`, wird `Frost erwartet` aktiv und bleibt es („sticky"), bis der Equipment-Abbau bestätigt wird.
- **Frühjahr:** Ab `spring_earliest_date` und ohne Frost in der Vorschau wird `Frühjahr bereit` aktiv, ebenfalls sticky.
- Die Bestätigung über `equipment_status_setzen` schaltet automatisch die Saison mit um und setzt die Bilanz zurück.
- **Zusätzlich, unabhängig vom Equipment-Thema:** Ist für die unmittelbar bevorstehende Nacht Frost zu erwarten, wird die Bewässerung für diesen Tag ausgesetzt (nasses Laub bei Frost ist schädlicher als trockenes) – nach demselben heute/morgen-Prinzip wie der Regen-Skip.

Die eigentliche Erinnerungs-Benachrichtigung ist **nicht** Teil der Integration, sondern eine Automation.

## Ausfallsicherheit und Fehlererkennung

- **Retry:** Schlägt der geplante Tageslauf fehl, bis zu 3 Versuche im 10-Minuten-Abstand. Jeder erfolgreiche Lauf wird mit ET0-Wert und Niederschlagsquelle geloggt (Info-Level).
- **Fallback:** Ist eine Quelle kurzzeitig `unavailable`, wird der letzte bekannte Wert verwendet (max. 26 h alt). Für echte Mitternachts-Zähler (PV-Ertrag) gilt eine Ausnahme: kein Fallback über Mitternacht hinweg, da der Zähler dort auf 0 zurückspringt. Rollierende Sensoren (z. B. der DWD-Regensensor) sind davon **nicht** betroffen.
- **Rollover-Nachholung:** Ein verpasster Tageswechsel wird beim nächsten Lauf automatisch nachgeholt.
- **Automatische Gesundheitsprüfung** (`Systemzustand`, seit v1.8.0): erkennt ausbleibende Berechnungen (>26 h), Buchungslücken, physikalisch unplausible ET0-Werte (jahreszeitabhängige Grenzen) und dauerhaften Fallback-Betrieb einzelner Quellen. Bewusst konservativ – meldet nur eindeutig Fehlerhaftes, keine bloß ungewöhnlichen Werte. Erscheint zusätzlich unter Einstellungen → Reparaturen und verschwindet automatisch, sobald behoben.
- **Diagnose-Attribute:** `fallback_werte_verwendet`, `laufender_tag`, `heutiger_beitrag_mm`, `neigungskorrektur_faktor`, `regen_prognose_heute_mm`/`_morgen_mm` und mehr an den jeweiligen Sensoren.

## Genauigkeit und Grenzen

Der PV-Proxy ersetzt keinen echten Strahlungssensor. Verbleibende Fehlerquellen nach der Neigungskorrektur:

- **Performance Ratio als fester Sammelwert** – enthält Temperaturverluste, die gerade an heißen Tagen (hoher Bedarf) stärker ausfallen
- **Verschmutzung, Verschattung, Schnee** – reduzieren den Ertrag ohne realen Strahlungsrückgang
- **Vereinfachtes Diffusmodell** – Direkt-/Diffusaufteilung wird korreliert, nicht gemessen

Realistische Größenordnung: grob **±10–15 %** an normalen Tagen, empirisch mit Verlaufsdaten gegengecheckt (klare Sommertage lagen im erwarteten Bereich von ~24–27 MJ/m²/Tag für die Jahreszeit). Für die Frage „muss heute gegossen werden und ungefähr wie viel" ausreichend; für wissenschaftlich belastbare ET0 nicht.

Wer es genauer will: eine Wetterstation mit **Solarstrahlungssensor** (W/m², nicht Lux) ersetzt den Proxy vollständig und liefert nebenbei gemessene Werte für Temperatur, Feuchte und Wind.

## Automationen

Die Ventilsteuerung läuft über normale HA-Automationen, die die Sensoren und Services dieser Integration nutzen. Sie sind bewusst **nicht** Teil des Repos, da hardware- und personenspezifisch:

- Gieß-Automation pro Zone – prüft `bewaesserung_erlaubt`, ruft nach dem Gießen `reset_deficit` mit der **netto** angekommenen Menge auf
- Gemeinsames Skript mit `mode: queued`, falls mehrere Zonen nicht gleichzeitig laufen dürfen (Wasserdruck) – inkl. Erfolgskontrolle (nur tatsächlich ausgebrachtes Wasser wird verbucht, kein Fehlschlag wird stillschweigend als „erledigt" gemeldet)
- Zusammenfassungs-Benachrichtigung, Frost-/Frühjahrs-Erinnerungen mit interaktiven Buttons
