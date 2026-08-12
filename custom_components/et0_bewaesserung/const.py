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
