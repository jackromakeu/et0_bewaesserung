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

# --- Zonen (seit v2.0.0 als Config-Subentries, nicht mehr indexbasiert) ---
# Jede Zone ist ein eigener Subentry mit eigenem Gerät. Die Anzahl ist
# dadurch nicht mehr begrenzt (früher MAX_ZONES = 3).
SUBENTRY_TYPE_ZONE = "zone"

CONF_ZONE_NAME = "name"
CONF_ZONE_KC = "kc"
CONF_ZONE_DRIP_RATE = "drip_rate"
CONF_ZONE_MIN_DAYS = "min_days"
CONF_ZONE_MIN_DEFICIT_MM = "min_deficit_mm"
CONF_ZONE_FIELD_CAPACITY = "field_capacity_mm"
CONF_ZONE_IRRIGATION_EFFICIENCY = "irrigation_efficiency"

# Kc: Verhältnis Pflanzenbedarf zu Referenzgras (FAO-56)
DEFAULT_ZONE_KC = 0.80
# mm Wasserabgabe pro Minute - MUSS an die eigene Anlage angepasst werden
DEFAULT_ZONE_DRIP_RATE = 0.25
# Mindestabstand in Tagen zwischen zwei Bewässerungen derselben Zone
DEFAULT_ZONE_MIN_DAYS = 1
# Mindest-Defizit in mm, ab dem überhaupt gegossen wird
DEFAULT_ZONE_MIN_DEFICIT_MM = 1.5
# Nutzbare Feldkapazität der Wurzelzone in mm - Obergrenze für das Defizit.
# Richtwerte: Sand 10-15, Lehm 20-30, Ton 25-35 mm.
DEFAULT_ZONE_FIELD_CAPACITY = 20.0
# Wirkungsgrad der Ausbringung: Anteil, der die Wurzelzone erreicht.
# Sprinkler ~0.75, Tropfschlauch ~0.85-0.95
DEFAULT_ZONE_IRRIGATION_EFFICIENCY = 0.75
# Untergrenze des Defizits als Anteil der Feldkapazität (siehe README)
DEFICIT_FLOOR_RATIO = 0.15


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
