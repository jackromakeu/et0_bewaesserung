"""Konstanten für die ET0-Bewässerungsintegration."""

DOMAIN = "et0_bewaesserung"

CONF_TEMP_MAX_ENTITY = "temp_max_entity"
CONF_TEMP_MIN_ENTITY = "temp_min_entity"
CONF_HUMIDITY_MEAN_ENTITY = "humidity_mean_entity"
CONF_WIND_MEAN_ENTITY = "wind_mean_entity"
CONF_PV_YIELD_ENTITY = "pv_yield_entity"
CONF_WEATHER_ENTITY = "weather_entity"

CONF_LATITUDE = "latitude"
CONF_ELEVATION = "elevation"
CONF_KWP = "kwp"
CONF_PERFORMANCE_RATIO = "performance_ratio"
CONF_UPDATE_TIME = "update_time"

DEFAULT_UPDATE_TIME = "23:30:00"
DEFAULT_PERFORMANCE_RATIO = 0.80
# --- PV-Geometrie für die Umrechnung Modulebene -> Horizontale ---
# Ohne diese Korrektur wird die Strahlung systematisch überschätzt, weil
# geneigte Module (besonders im Winter) mehr Einstrahlung erhalten als eine
# horizontale Fläche. 0 = Korrektur deaktiviert (Verhalten wie vor v1.7.0).
CONF_PV_TILT = "pv_tilt"
DEFAULT_PV_TILT = 35.0
CONF_PV_AZIMUTH = "pv_azimuth"
DEFAULT_PV_AZIMUTH = 0.0  # 0 = Süd, -90 = Ost, +90 = West
ALBEDO = 0.23

STORAGE_VERSION = 1
STORAGE_KEY = f"{DOMAIN}_deficit"

# --- Zonen (Kc-Faktor pro Bewässerungsbereich) ---
MAX_ZONES = 3
DEFAULT_ZONE_NAMES = ["Rasen", "Beete", "Hecken"]
# Kc-Startwerte nach FAO-56, grobe Richtwerte - je nach Bepflanzung anpassen
DEFAULT_ZONE_KC = [0.90, 1.00, 0.50]
# mm Wasserabgabe pro Minute - MUSS an die eigene Anlage angepasst werden
DEFAULT_ZONE_DRIP_RATE = [0.25, 0.20, 0.15]
# Mindestabstand in Tagen zwischen zwei Bewässerungen derselben Zone -
# Standard 1 = aktuelles Verhalten unverändert (max. 1x/Tag durch Tages-Sperre)
DEFAULT_ZONE_MIN_DAYS = [1, 1, 1]
# Mindest-Defizit in mm, ab dem überhaupt gegossen wird - verhindert
# Bewässerung bei nur geringfügigem Wasserbedarf
DEFAULT_ZONE_MIN_DEFICIT_MM = [1.5, 1.5, 1.5]
# Nutzbare Feldkapazität der Wurzelzone in mm - Obergrenze für das Defizit.
# Mehr Wasser als das kann der Boden nicht halten; alles darüber versickert
# unterhalb der Wurzeln und ist verloren. Richtwerte: Sand 10-15, Lehm 20-30,
# Ton 25-35 mm bei üblicher Rasendurchwurzelung. Konservativ = niedriger
# Wert (führt zu häufigerem, kleinerem Gießen statt seltener Überwässerung).
DEFAULT_ZONE_FIELD_CAPACITY = [20.0, 20.0, 20.0]
# Untergrenze des Defizits, als ANTEIL der Feldkapazität. Ein negatives
# Defizit bedeutet "Boden voller als der Zielzustand" - der Boden kann aber
# nicht beliebig viel speichern: ist die Feldkapazität erreicht, läuft
# zusätzliches Wasser durch die Wurzelzone hindurch ab (Perkolation) und ist
# für die Pflanze verloren. Fachlich wäre 0 die exakte Grenze; der kleine
# negative Puffer bildet Messungenauigkeit (Radar-Näherung,
# Wirksamkeitsfaktor) und Restreserve tieferer Bodenschichten ab.
# Zuvor war das eine feste Konstante von -10 mm, die unabhängig von der
# Bodenart galt und nach Regenphasen zu spätem Gießen führen konnte.
DEFICIT_FLOOR_RATIO = 0.15
# Wirkungsgrad der Ausbringung: welcher Anteil kommt in der Wurzelzone an?
# Sprinkler/Rotoren verlieren durch Windabdrift, Verdunstung und ungleiche
# Verteilung typisch 20-30%; Tropfschläuche kaum (0.9-0.95).
# Konservativ = niedriger Wert (es wird MEHR ausgebracht, um das Defizit
# rechnerisch zu decken).
DEFAULT_ZONE_IRRIGATION_EFFICIENCY = [0.75, 0.85, 0.75]


def zone_key(index: int, field: str) -> str:
    """Baut den Config-Key für ein Zonen-Feld, z.B. zone_0_name."""
    return f"zone_{index}_{field}"


# --- Vorausschauender Regen-Skip ---
CONF_RAIN_SKIP_ENABLED = "rain_skip_enabled"
CONF_RAIN_SKIP_THRESHOLD = "rain_skip_threshold_mm"
DEFAULT_RAIN_SKIP_ENABLED = True
DEFAULT_RAIN_SKIP_THRESHOLD = 5.0

# --- Niederschlagsanrechnung in der Tagesbilanz ---
# Optionaler Sensor mit GEMESSENER Tagesniederschlagsmenge (mm), z.B. von
# einer eigenen Wetterstation. Ist er gesetzt, hat er Vorrang vor der
# Vorhersage - gemessen schlägt prognostiziert.
CONF_RAIN_SENSOR = "rain_sensor_entity"
# Wirksamkeitsfaktor: welcher Anteil des Niederschlags kommt tatsächlich in
# der Wurzelzone an? Bei Starkregen fließt ein Teil oberflächlich ab.
# 1.0 = voll anrechnen (spart Wasser, gießt seltener)
# 0.7-0.8 = konservativ (gießt häufiger, Risiko der Unterversorgung geringer)
CONF_RAIN_EFFECTIVENESS = "rain_effectiveness"
DEFAULT_RAIN_EFFECTIVENESS = 1.0

# --- Ausfallsicherheit beim geplanten Tageslauf ---
RETRY_DELAY_MINUTES = 10
MAX_RETRIES = 3

# --- TEMPORÄRER DIAGNOSE-MODUS ---
# True: läuft stündlich zur konfigurierten Minute (statt nur 1x täglich).
# War zur Fehlersuche bei den PV-Sensor-Ausfallzeiten aktiv, jetzt wieder
# auf den Normalbetrieb (1x täglich) zurückgestellt.
DIAGNOSE_MODE = False

# --- Fallback auf letzten bekannten Wert bei kurzzeitig nicht verfügbaren Quellen ---
FALLBACK_MAX_AGE_HOURS = 26

# --- Frost-Erkennung (Herbst -> Equipment-Abbau) ---
CONF_FROST_LOOKAHEAD_DAYS = "frost_lookahead_days"
DEFAULT_FROST_LOOKAHEAD_DAYS = 3
CONF_FROST_THRESHOLD = "frost_threshold_c"
DEFAULT_FROST_THRESHOLD = 1.0  # °C - leicht über 0 für Vorwarnzeit

# --- Frühjahrs-Erkennung (Equipment-Wiederaufbau) ---
CONF_SPRING_EARLIEST_DATE = "spring_earliest_date"  # Format "MM-DD"
DEFAULT_SPRING_EARLIEST_DATE = "03-01"
