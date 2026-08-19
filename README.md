# ET0 Bewässerung

Lokale Home-Assistant-Integration für evapotranspirationsbasierte Gartenbewässerung nach **FAO-56 Penman-Monteith** – ohne Bodenfeuchtesensoren. Die benötigte Solarstrahlung wird näherungsweise aus dem Ertrag einer vorhandenen PV-Anlage abgeleitet, statt einen eigenen Pyranometer zu erfordern.

## Inhaltsverzeichnis

- [Funktionsprinzip](#funktionsprinzip)
- [Datenmodell](#datenmodell)
- [Voraussetzungen](#voraussetzungen)
- [Installation](#installation)
- [Konfiguration](#konfiguration)
- [Entitäten](#entitäten)
- [Services](#services)
- [Zonen: Kc, Tropfrate, Mindestwerte](#zonen-kc-tropfrate-mindestwerte)
- [Regen: Skip und Anrechnung](#regen-skip-und-anrechnung)
- [PV-Näherung und Neigungskorrektur](#pv-näherung-und-neigungskorrektur)
- [Frost- und Saisonmanagement](#frost--und-saisonmanagement)
- [Ausfallsicherheit](#ausfallsicherheit)
- [Genauigkeit und Grenzen](#genauigkeit-und-grenzen)
- [Automationen](#automationen)

## Funktionsprinzip

1. **ET0-Berechnung** einmal täglich (abends, wenn der PV-Tagesertrag vollständig ist) nach FAO-56 Penman-Monteith aus Tages-Min/Max-Temperatur, mittlerer Luftfeuchte, mittlerem Wind und der aus dem PV-Ertrag abgeleiteten Solarstrahlung.
2. **Pro Zone** wird ETc = ET0 × Kc berechnet, abzüglich angerechnetem Niederschlag.
3. **Beim Tageswechsel** wandert der Tagesbeitrag in das Defizit der abgeschlossenen Tage – das ist die Basis für die morgendliche Bewässerung.
4. **Nach dem Gießen** meldet eine Automation die abgegebene Menge zurück; sie wird vom Defizit abgezogen (nicht auf 0 gesetzt, siehe unten).

## Datenmodell

Zentral für das Verständnis – seit v1.4.0:

| Größe | Bedeutung |
|---|---|
| **carry** | Defizit **abgeschlossener** Tage, abzüglich Bewässerung. Basis für die Gieß-Entscheidung. Sichtbar als `Bewässerungsdefizit <Zone>`. |
| **today** | ETc − Niederschlag des **laufenden** Tages. Wird bei jeder Berechnung **überschrieben**, nie addiert. |
| **Rollover** | Um 00:00:30 wandert `today` nach `carry`. Zusätzlich wird bei jeder Berechnung geprüft, ob ein Tageswechsel verpasst wurde (HA-Neustart o.ä.) und ggf. nachgeholt. |

Weil `today` überschrieben statt addiert wird, ist die Berechnung **idempotent**: Sie kann beliebig oft am selben Tag laufen, ohne die Bilanz zu verfälschen. Eine „Tages-Sperre" wie in früheren Versionen ist dadurch überflüssig.

**Restmengen gehen nicht verloren:** Beim Zurückmelden einer Bewässerung wird die tatsächlich abgegebene Menge abgezogen. Wer bei 4,2 mm Bedarf nur 3 mm abgibt (z.B. wegen fester Dosisstufen), behält 1,2 mm im Defizit – am nächsten Tag wird darauf aufgebaut.

## Voraussetzungen

- Home Assistant mit aktivem `recorder`
- Eine `weather.*`-Entity mit Unterstützung für `weather.get_forecasts` (für Niederschlag und Frostvorschau)
- Sensoren für: Tages-Maximaltemperatur, Tages-Minimaltemperatur, mittlere Luftfeuchte, mittlere Windgeschwindigkeit (km/h), PV-Tagesertrag (kWh, **täglich auf 0 zurückgesetzter Zähler**, kein Lifetime-Zähler)
- PV-Anlage mit bekannter Nennleistung

Die vier Wetter-Sensoren lassen sich z.B. als Template- plus Statistics-Sensoren aus einer `weather`-Entity ableiten.

## Installation

**Über HACS:** HACS → „⋮" → Benutzerdefinierte Repositories → URL eintragen, Kategorie „Integration" → installieren → Home Assistant neu starten.

**Manuell:** Ordner `custom_components/et0_bewaesserung` nach `/config/custom_components/` kopieren, Home Assistant **vollständig** neu starten.

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
| `pv_tilt` / `pv_azimuth` | Dachneigung (Grad) und Ausrichtung (0 = Süd), siehe unten |
| `update_time` | Uhrzeit der täglichen Berechnung (`HH:MM` oder `HH:MM:SS`) |
| `rain_skip_enabled` / `rain_skip_threshold_mm` | vorausschauender Regen-Skip |
| `rain_sensor_entity` | gemessener Tagesniederschlag (optional, hat Vorrang) |
| `rain_effectiveness` | Anteil des Regens, der die Wurzelzone erreicht |
| `frost_lookahead_days` / `frost_threshold_c` | Frost-Vorwarnung |
| `spring_earliest_date` | frühestes Frühjahrsdatum (`MM-TT`) |

**Schritt 2 – Zonen** (bis zu 3, Name leer = deaktiviert): `name`, `kc`, `drip_rate`, `min_days`, `min_deficit_mm`.

## Entitäten

Alle Entitäten hängen an einem gemeinsamen Gerät „ET0 Bewässerung".

**Global**

| Entität | Typ | Beschreibung |
|---|---|---|
| ET0 Tagesreferenz | sensor | Tages-ET0 (mm) inkl. umfangreicher Diagnose-Attribute |
| Solarstrahlung (PV-Proxy) | sensor | Aus PV-Ertrag abgeleitete Globalstrahlung (MJ/m²) |
| ET0 Saisonsumme | sensor | Kumulierte Verdunstung seit Saisonstart (Statistik, keine Bilanz) |
| Gartensaison aktiv | switch | Aus = komplette Logik pausiert, Bilanz wird zurückgesetzt |
| Regen erwartet (Skip aktiv) | binary_sensor | Regen-Skip für morgen aktiv |
| Frost erwartet – Equipment-Abbau nötig | binary_sensor | „Sticky" bis Bestätigung |
| Frühjahr bereit – Equipment-Aufbau möglich | binary_sensor | „Sticky" bis Bestätigung |
| Equipment verstaut | binary_sensor | An = Winterkonfiguration |
| Jetzt neu berechnen | button | Manuelle Neuberechnung, seit v1.4.0 jederzeit unschädlich (idempotent) |

**Pro Zone**

| Entität | Beschreibung |
|---|---|
| ETc `<Zone>` | Wasserbedarf des laufenden Tages (mm) |
| Bewässerungsdefizit `<Zone>` | **Basis für die Gieß-Entscheidung** (abgeschlossene Tage) |
| Defizit laufend `<Zone>` | inkl. laufendem Tag – bewegt sich über den Tag |
| Bewässerungsdauer `<Zone>` | Empfohlene Gießdauer (min); 0 wenn nicht freigegeben |
| Zuletzt bewässert `<Zone>` | Zeitstempel, Attribut `menge_mm` |
| Mindestabstand erfüllt `<Zone>` | binary_sensor, für die Fehlersuche |
| Mindestdefizit erfüllt `<Zone>` | binary_sensor, für die Fehlersuche |

**Wichtigstes Attribut:** `bewaesserung_erlaubt` an `Bewässerungsdauer <Zone>` fasst Regen-Skip, Mindestabstand und Mindestdefizit zu einem Flag zusammen – Automationen brauchen nur diese eine Bedingung.

## Services

### `et0_bewaesserung.recalculate`
Sofortige Neuberechnung. Beliebig oft wiederholbar (idempotent).

### `et0_bewaesserung.reset_deficit`
| Feld | Beschreibung |
|---|---|
| `zone` | Zonenname. Ohne Angabe: globaler Reset aller Zonen. |
| `amount_mm` | Abgegebene Menge – wird vom Defizit **abgezogen** und in der Historie gespeichert. Ohne Angabe: hart auf 0. |

Der Zonen-Name wird unicode-normalisiert verglichen (Umlaute funktionieren unabhängig von der Eingabequelle).

### `et0_bewaesserung.equipment_status_setzen`
| Feld | Beschreibung |
|---|---|
| `verstaut` | `true` = verstaut (schaltet Saison aus), `false` = aufgebaut (schaltet Saison an) |

## Zonen: Kc, Tropfrate, Mindestwerte

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

**`min_days`** – Mindestabstand zwischen zwei Bewässerungen (Standard 1). Höhere Werte fördern seltenes, dafür tieferes Gießen und damit tieferes Wurzelwachstum.

**`min_deficit_mm`** – Mindestdefizit, ab dem überhaupt gegossen wird (Standard 1,5). Verhindert Bewässerung bei geringfügigem Bedarf; das Defizit sammelt sich stattdessen weiter an.

## Regen: Skip und Anrechnung

Zwei getrennte Mechanismen:

**Regen-Skip (vorausschauend):** Liegt die Niederschlagsprognose für **morgen** über `rain_skip_threshold_mm`, wird `Bewässerungsdauer` auf 0 gesetzt. Die Bilanz läuft unverändert weiter – nur der Trigger wird ausgesetzt.

**Anrechnung in der Bilanz:** Der Niederschlag des **heutigen** Tages wird vom Tagesbeitrag abgezogen. Quellen in dieser Reihenfolge:
1. `rain_sensor_entity` (gemessen, z.B. eigene Wetterstation) – hat Vorrang
2. Tagessumme aus `weather.get_forecasts`

Der Wert wird mit `rain_effectiveness` gewichtet: Bei Starkregen fließt ein Teil oberflächlich ab statt zu versickern. `1.0` rechnet voll an (spart Wasser), `0.7–0.8` ist konservativ (gießt häufiger).

Das Attribut `niederschlag_quelle` an `ET0 Saisonsumme` zeigt, welche Quelle tatsächlich verwendet wurde.

## PV-Näherung und Neigungskorrektur

PV-Module messen die Einstrahlung auf die **geneigte Modulebene**; FAO-56 benötigt die **horizontale** Fläche. Ohne Korrektur wird ET0 systematisch überschätzt.

Die Integration rechnet um über: Rb-Geometriefaktor nach Liu & Jordan (Tageswerte), Diffusanteil nach Erbs-Korrelation aus dem Clearness-Index, isotropes Himmelsmodell für Diffus- und Bodenreflexion, iterativ gelöst.

Größenordnung bei 35° Süd (Faktor = Modulebene ÷ Horizontale):

| Zeitraum | Faktor |
|---|---|
| Hochsommer | ~1,02 |
| Frühjahr / Herbst | ~1,13 – 1,17 |
| Bewölkt | < 1,0 (Diffusanteil dominiert) |

`pv_tilt = 0` deaktiviert die Korrektur. Bei Ost-West-Anlagen oder mehreren unterschiedlich ausgerichteten Teilflächen ist sie nicht anwendbar.

## Frost- und Saisonmanagement

- **Herbst:** Sinkt die Tiefsttemperatur-Prognose innerhalb von `frost_lookahead_days` unter `frost_threshold_c`, wird `Frost erwartet` aktiv und bleibt es („sticky"), bis der Equipment-Abbau bestätigt wird.
- **Frühjahr:** Ab `spring_earliest_date` und ohne Frost in der Vorschau wird `Frühjahr bereit` aktiv, ebenfalls sticky.
- Die Bestätigung über `equipment_status_setzen` schaltet automatisch die Saison mit um und setzt die Bilanz zurück.

Die eigentliche Erinnerungs-Benachrichtigung ist **nicht** Teil der Integration, sondern eine Automation (interaktive Push-Buttons sind Automations-Territorium).

## Ausfallsicherheit

- **Retry:** Schlägt der geplante Tageslauf fehl, bis zu 3 Versuche im 10-Minuten-Abstand.
- **Fallback:** Ist eine Quelle kurzzeitig `unavailable`, wird der letzte bekannte Wert verwendet (max. 26h alt). Für Tageszähler (PV-Ertrag, Regensensor) gilt eine Ausnahme: **kein** Fallback über Mitternacht, da der Zähler dort auf 0 zurückspringt.
- **Rollover-Nachholung:** Ein verpasster Tageswechsel (Neustart, Update, Stromausfall um Mitternacht) wird beim nächsten Lauf automatisch nachgeholt.
- **Diagnose:** `fallback_werte_verwendet`, `laufender_tag`, `heutiger_beitrag_mm`, `neigungskorrektur_faktor`, `niederschlag_quelle` machen den internen Zustand sichtbar.

## Genauigkeit und Grenzen

Der PV-Proxy ersetzt keinen echten Strahlungssensor. Verbleibende Fehlerquellen nach der Neigungskorrektur:

- **Performance Ratio als fester Sammelwert** – enthält Temperaturverluste, die aber gerade an heißen Tagen (hoher Bedarf) stärker ausfallen
- **Verschmutzung, Verschattung, Schnee** – reduzieren den Ertrag ohne realen Strahlungsrückgang
- **Vereinfachtes Diffusmodell** – Direkt-/Diffusaufteilung wird korreliert, nicht gemessen

Realistische Größenordnung: grob **±10–15 %** an normalen Tagen. Für die Frage „muss heute gegossen werden und ungefähr wie viel" ausreichend; für wissenschaftlich belastbare ET0 nicht.

Wer es genauer will: eine Wetterstation mit **Solarstrahlungssensor** (W/m², nicht Lux) ersetzt den Proxy vollständig und liefert nebenbei gemessene Werte für Temperatur, Feuchte, Wind und Regen.

## Automationen

Die Ventilsteuerung läuft über normale HA-Automationen, die die Sensoren und Services dieser Integration nutzen. Sie sind bewusst **nicht** Teil des Repos, da hardware- und personenspezifisch:

- Gieß-Automation pro Zone – prüft `bewaesserung_erlaubt`, ruft nach dem Gießen `reset_deficit` mit `amount_mm` auf
- Gemeinsames Skript mit `mode: queued`, falls mehrere Zonen nicht gleichzeitig laufen dürfen (Wasserdruck)
- Zusammenfassungs-Benachrichtigung, Frost-/Frühjahrs-Erinnerungen mit interaktiven Buttons
