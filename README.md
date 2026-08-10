# ET0 Bewässerung

Lokale Home-Assistant-Integration für evapotranspirationsbasierte Gartenbewässerung nach **FAO-56 Penman-Monteith** – ganz ohne Bodenfeuchtesensoren. Die benötigte Solarstrahlung wird dabei näherungsweise aus dem Ertrag einer vorhandenen PV-Anlage abgeleitet, statt einen eigenen Pyranometer-Sensor zu benötigen.

## Inhaltsverzeichnis

- [Funktionsprinzip](#funktionsprinzip)
- [Voraussetzungen](#voraussetzungen)
- [Installation](#installation)
- [Einrichtung](#einrichtung)
- [Entitäten](#entitäten)
- [Services (Aktionen)](#services-aktionen)
- [Zonen & Kc-Faktor](#zonen--kc-faktor)
- [Regen-Skip](#regen-skip)
- [Frost-/Frühjahrs-Erkennung](#frost-frühjahrs-erkennung)
- [Ausfallsicherheit](#ausfallsicherheit)
- [Bekannte Einschränkungen](#bekannte-einschränkungen)
- [Bewässerungs-Automationen (nicht Teil dieses Repos)](#bewässerungs-automationen-nicht-teil-dieses-repos)

## Funktionsprinzip

1. **ET0-Berechnung**: Einmal täglich wird die Referenz-Evapotranspiration (ET0, mm/Tag) nach FAO-56 Penman-Monteith berechnet, aus Tages-Min/Max-Temperatur, mittlerer Luftfeuchte, mittlerem Wind und einer aus dem PV-Tagesertrag abgeleiteten Solarstrahlung.
2. **Wasserbilanz je Zone**: Für jede konfigurierte Zone (z.B. Rasen, Beete) wird ETc = ET0 × Kc berechnet und als tägliches Defizit aufsummiert (abzüglich gefallenem/vorhergesagtem Niederschlag).
3. **Bewässerungsdauer**: Aus Defizit ÷ Tropfrate der jeweiligen Zone ergibt sich eine empfohlene Bewässerungsdauer in Minuten – nutzbar von eigenen Automationen zur Ventilsteuerung.
4. **Reset nach Bewässerung**: Eine Automation ruft nach dem Gießen den Service `reset_deficit` auf; die Bilanz startet wieder bei 0.

## Voraussetzungen

- Home Assistant mit `recorder` aktiv
- Eine `weather.*`-Entity mit Unterstützung für `weather.get_forecasts` (für Niederschlags- und Frost-Vorhersage)
- Sensoren für: Tages-Maximaltemperatur, Tages-Minimaltemperatur, mittlere Luftfeuchte, mittlere Windgeschwindigkeit (km/h), PV-Tagesertrag (kWh, **täglich auf 0 zurückgesetzter Zähler**, kein Lifetime-Zähler!)
- Eine PV-Anlage mit bekannter Nennleistung (kWp)

## Installation

### Über HACS (empfohlen)

1. HACS → Integrationen → „⋮" → „Benutzerdefinierte Repositories"
2. Repository-URL eintragen, Kategorie „Integration"
3. „ET0 Bewässerung" installieren, Home Assistant neu starten

### Manuell

1. Diesen Ordner `custom_components/et0_bewaesserung` nach `/config/custom_components/` kopieren
2. Home Assistant komplett neu starten (nicht nur „Konfiguration neu laden")

## Einrichtung

Einstellungen → Geräte & Dienste → „Integration hinzufügen" → „ET0 Bewässerung"

Der Einrichtungsdialog läuft in zwei Schritten:

**Schritt 1 – Allgemein:**
- 5 Pflicht-Sensoren (Temp-Max/Min, Feuchte, Wind, PV-Ertrag)
- Optional: Wetter-Entity (für Niederschlag/Frost)
- Breitengrad/Höhe (werden aus der HA-Standortkonfiguration vorbefüllt)
- PV-Nennleistung (kWp) und Performance Ratio
- Uhrzeit der täglichen Berechnung
- Regen-Skip (an/aus + Schwelle in mm)
- Frost-Vorwarnzeit (Tage), Frost-Schwelle (°C), frühestes Frühjahrs-Datum

**Schritt 2 – Zonen:** bis zu 3 Zonen, je mit Name (leer = deaktiviert), Kc-Faktor und Tropfrate (mm/min).

Alle Werte lassen sich später jederzeit über „Konfigurieren" anpassen – inklusive erneuter Validierung der gewählten Entities.

## Entitäten

Alle Entitäten hängen an einem gemeinsamen Gerät „ET0 Bewässerung".

| Entity | Domain | Beschreibung |
|---|---|---|
| ET0 Tagesreferenz | sensor | Tages-ET0 (mm), inkl. Diagnose-Attributen (Rs, Rn, Tmean, u2, Regenprognose, verwendete Fallback-Werte) |
| Solarstrahlung (PV-Proxy) | sensor | Aus PV-Ertrag abgeleitete Globalstrahlung (MJ/m²) |
| Bewässerungsdefizit | sensor | Globale Referenzbilanz (Kc=1) |
| ETc `<Zone>` | sensor | Tatsächlicher Wasserbedarf der Zone (mm) |
| Bewässerungsdefizit `<Zone>` | sensor | Aufgelaufenes Defizit der Zone (mm) |
| Bewässerungsdauer `<Zone>` | sensor | Empfohlene Gießdauer (Minuten), 0 bei Regen-Skip |
| Zuletzt bewässert `<Zone>` | sensor | Zeitstempel + Menge (mm) der letzten Bewässerung |
| Gartensaison aktiv | switch | Pausiert bei „aus" die komplette Logik (setzt Bilanz zurück) |
| Frost erwartet - Equipment-Abbau nötig | binary_sensor | „Sticky" bis Equipment als verstaut bestätigt |
| Frühjahr bereit - Equipment-Aufbau möglich | binary_sensor | „Sticky" bis Equipment als aufgebaut bestätigt |
| Equipment verstaut | binary_sensor | Aktueller Status (an = Winterkonfiguration) |

## Services (Aktionen)

### `et0_bewaesserung.recalculate`
Stößt eine sofortige Neuberechnung an. Wirft bei Fehlschlag einen sichtbaren Fehler mit der genauen Ursache.

### `et0_bewaesserung.reset_deficit`
| Feld | Pflicht | Beschreibung |
|---|---|---|
| `zone` | nein | Zonenname. Ohne Angabe: globaler Reset (alle Zonen + Referenz, löst auch die Tages-Sperre). |
| `amount_mm` | nein | Abgegebene Menge, wird im „Zuletzt bewässert"-Verlauf gespeichert. |

### `et0_bewaesserung.equipment_status_setzen`
| Feld | Pflicht | Beschreibung |
|---|---|---|
| `verstaut` | ja | `true` = Equipment verstaut (schaltet Saison automatisch aus), `false` = wieder aufgebaut (schaltet Saison automatisch an). |

## Zonen & Kc-Faktor

Kc (Crop Coefficient) skaliert die Referenz-ET0 auf den tatsächlichen Bedarf der Pflanzenart. FAO-56-Richtwerte:

| Bepflanzung | Typischer Kc |
|---|---|
| Rasen | 0,80 – 0,90 |
| Beete / Gemüse | 0,90 – 1,15 |
| Sträucher / Hecken (etabliert) | 0,40 – 0,60 |

Die **Tropfrate** (mm Wasserabgabe pro Minute) muss anhand der eigenen Bewässerungsanlage kalibriert werden:

```
Tropfrate [mm/min] = (Durchfluss pro Tropfer [L/h] × Tropfer pro m²) / 60
```

## Regen-Skip

Nutzt `weather.get_forecasts` (Typ „daily"), prüft die Niederschlagsprognose für **morgen**. Übersteigt sie die konfigurierte Schwelle, wird `Bewässerungsdauer` alle Zonen auf 0 gesetzt – die Bilanz selbst läuft unverändert weiter (nichts geht verloren, nur der Trigger wird ausgesetzt).

## Frost-/Frühjahrs-Erkennung

Prüft bei jedem Lauf die Tiefsttemperatur-Vorhersage der kommenden `frost_lookahead_days` Tage:

- **Herbst**: Sinkt ein Wert unter die Frost-Schwelle, während die Saison aktiv und das Equipment noch nicht verstaut ist, wird `binary_sensor.frost_erwartet...` aktiv ("sticky", bleibt an bis Bestätigung).
- **Frühjahr**: Ab dem konfigurierten Frühestdatum UND ohne Frost in der Vorschau wird `binary_sensor.fruehjahr_bereit...` aktiv (ebenfalls sticky).
- Die Bestätigung erfolgt über den Service `equipment_status_setzen` und schaltet automatisch die Saison mit um.

Die eigentliche tägliche Erinnerungs-Benachrichtigung (inkl. Bestätigungs-Buttons) ist **nicht** Teil dieser Integration, sondern eine separate HA-Automation (siehe unten) – Push-Benachrichtigungen mit interaktiven Buttons sind Automations-, nicht Integrations-Territorium.

## Ausfallsicherheit

- **Retry**: Schlägt der geplante Tageslauf fehl, werden bis zu 3 Versuche im 10-Minuten-Abstand unternommen.
- **Fallback auf letzten bekannten Wert**: Ist eine Quelle kurzzeitig `unavailable`/`unknown`, wird (max. 26h alt) der letzte bekannte Wert verwendet. Für den PV-Ertragssensor (Tages-Zähler) gilt eine Ausnahme: der Fallback wird **nicht** über eine Mitternachtsgrenze hinweg verwendet, da der Zähler dort auf 0 zurückspringt.
- **Tages-Sperre**: Die Bilanz wird pro Kalendertag nur einmal fortgeschrieben, egal wie oft manuell neu berechnet oder Home Assistant neu gestartet wird.

## Bekannte Einschränkungen

- Die Solarstrahlung wird nur näherungsweise aus dem PV-Ertrag abgeleitet (keine Berücksichtigung von Dachneigung/-ausrichtung) – für Bewässerungszwecke ausreichend genau, nicht wissenschaftlich präzise.
- `DIAGNOSE_MODE` in `const.py`: auf `True` gesetzt läuft die Berechnung stündlich statt täglich (für Fehlersuche bei instabilen Quellen). **Für den Normalbetrieb auf `False` setzen.**
- Maximal 3 Zonen (durch `MAX_ZONES` in `const.py` erweiterbar, aber ungetestet über 3 hinaus).
- Kein eigenes Frontend-Dashboard enthalten – siehe Lovelace-Beispiel-YAML im Repo (falls vorhanden) bzw. eigene Dashboard-Konfiguration.

## Bewässerungs-Automationen (nicht Teil dieses Repos)

Die tatsächliche Ventilsteuerung läuft über normale Home-Assistant-Automationen, die auf die Sensoren/Services dieser Integration zugreifen, aber bewusst **nicht** in diesem Repo liegen (hardware-/personenspezifisch, keine wiederverwendbare Integrationslogik):

- Gieß-Automation pro Zone (nutzt `Bewässerungsdauer`/`Bewässerungsdefizit`, ruft nach dem Gießen `reset_deficit` auf)
- Morgendliche Zusammenfassungs-Benachrichtigung
- Frost-/Frühjahrs-Erinnerungen mit actionable Buttons (rufen `equipment_status_setzen` auf)

Diese Automationen liegen in der privaten Home-Assistant-Konfiguration, nicht in diesem öffentlichen/teilbaren Integrations-Repo.
