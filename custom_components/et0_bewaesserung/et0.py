"""FAO-56 Penman-Monteith Berechnung (reine Funktion, keine HA-Abhängigkeiten)."""

from __future__ import annotations

import math
from datetime import date


def poa_to_horizontal(
    h_poa: float,
    latitude: float,
    tilt: float,
    azimuth: float,
    calc_date: date,
    albedo_ground: float = 0.2,
) -> tuple[float, float]:
    """Rechnet die Tagessumme von der Modulebene (POA) auf die Horizontale um.

    Die PV-Anlage misst indirekt die Einstrahlung auf die GENEIGTE
    Modulebene. FAO-56 benötigt aber die Strahlung auf die HORIZONTALE
    Fläche (der Rasen liegt flach). Bei 35° Dachneigung liegt die
    Modulebenen-Einstrahlung im Sommer typisch 5-15% über der
    horizontalen, im Winter deutlich mehr - ohne Korrektur wird ET0
    dadurch systematisch überschätzt.

    Verfahren (Standardansatz der Solarenergietechnik):
    - Rb (Direktstrahlungs-Geometriefaktor) nach Liu & Jordan für Tageswerte
    - Diffusanteil nach Erbs-Korrelation aus dem Clearness-Index Kt
    - Isotropes Himmelsmodell für Diffus- und Bodenreflexionsanteil
    - Da Kt vom gesuchten Horizontalwert abhängt, wird iteriert (konvergiert
      nach wenigen Durchläufen)

    Gibt (h_horizontal, faktor) zurück; faktor = h_poa / h_horizontal.
    """
    lat_rad = math.radians(latitude)
    tilt_rad = math.radians(tilt)
    doy = calc_date.timetuple().tm_yday

    # Extraterrestrische Tagessumme auf die Horizontale (MJ/m²)
    dr = 1 + 0.033 * math.cos(2 * math.pi / 365 * doy)
    decl = 0.409 * math.sin(2 * math.pi / 365 * doy - 1.39)
    ws = math.acos(max(-1.0, min(1.0, -math.tan(lat_rad) * math.tan(decl))))
    ra = (24 * 60 / math.pi) * 0.0820 * dr * (
        ws * math.sin(lat_rad) * math.sin(decl)
        + math.cos(lat_rad) * math.cos(decl) * math.sin(ws)
    )
    if ra <= 0 or h_poa <= 0:
        return h_poa, 1.0

    # --- Rb: Geometriefaktor der Direktstrahlung (Liu & Jordan, Tageswert) ---
    # Für äquatorwärts geneigte Flächen; der Azimut geht über eine effektive
    # Neigung ein (Näherung, für nahezu-Süd-Ausrichtung gut brauchbar).
    lat_eff = lat_rad - tilt_rad
    ws_tilt = min(
        ws, math.acos(max(-1.0, min(1.0, -math.tan(lat_eff) * math.tan(decl))))
    )
    num = (
        math.cos(lat_eff) * math.cos(decl) * math.sin(ws_tilt)
        + ws_tilt * math.sin(lat_eff) * math.sin(decl)
    )
    den = (
        math.cos(lat_rad) * math.cos(decl) * math.sin(ws)
        + ws * math.sin(lat_rad) * math.sin(decl)
    )
    rb = num / den if den > 0 else 1.0
    # Azimut-Abweichung von Süd dämpft den Direktstrahlungsgewinn
    rb *= math.cos(math.radians(azimuth)) ** 0.5 if azimuth else 1.0
    rb = max(rb, 0.1)

    # --- Iterativ: Diffusanteil hängt von Kt ab, Kt vom gesuchten H ---
    h_horiz = h_poa  # Startwert
    factor = 1.0
    for _ in range(6):
        kt = max(0.0, min(1.0, h_horiz / ra))
        # Erbs-Korrelation: Diffusanteil der Tagessumme
        if kt <= 0.22:
            hd_h = 1.0 - 0.09 * kt
        elif kt <= 0.80:
            hd_h = (
                0.9511
                - 0.1604 * kt
                + 4.388 * kt**2
                - 16.638 * kt**3
                + 12.336 * kt**4
            )
        else:
            hd_h = 0.165
        hd_h = max(0.0, min(1.0, hd_h))

        factor = (
            (1 - hd_h) * rb
            + hd_h * (1 + math.cos(tilt_rad)) / 2
            + albedo_ground * (1 - math.cos(tilt_rad)) / 2
        )
        factor = max(factor, 0.3)
        h_new = h_poa / factor
        if abs(h_new - h_horiz) < 0.01:
            h_horiz = h_new
            break
        h_horiz = h_new

    return h_horiz, factor


def calculate_et0(
    tmax: float,
    tmin: float,
    rh_mean: float,
    wind_mean_kmh: float,
    pv_yield_kwh: float,
    kwp: float,
    performance_ratio: float,
    latitude: float,
    elevation: float,
    albedo: float = 0.23,
    calc_date: date | None = None,
    tilt: float | None = None,
    azimuth: float = 0.0,
) -> dict:
    """Berechnet ET0 (mm/Tag) und liefert Zwischenwerte zur Diagnose zurück."""

    calc_date = calc_date or date.today()
    tmean = (tmax + tmin) / 2
    u2 = wind_mean_kmh / 3.6 * 0.748  # km/h -> m/s, Höhenkorrektur 10m -> 2m

    # --- Rs aus PV-Ertrag ableiten (Näherung) ---
    h_poa_kwh_m2 = pv_yield_kwh / (kwp * performance_ratio)
    rs_poa = h_poa_kwh_m2 * 3.6  # kWh/m2 -> MJ/m2/Tag (auf der MODULEBENE)

    # Modulebene -> Horizontale (FAO-56 braucht die horizontale Fläche)
    if tilt is not None and tilt > 0:
        rs, transposition_factor = poa_to_horizontal(
            rs_poa, latitude, tilt, azimuth, calc_date
        )
    else:
        rs, transposition_factor = rs_poa, 1.0

    # --- Astronomische Größen ---
    doy = calc_date.timetuple().tm_yday
    lat_rad = math.radians(latitude)

    dr = 1 + 0.033 * math.cos(2 * math.pi / 365 * doy)
    decl = 0.409 * math.sin(2 * math.pi / 365 * doy - 1.39)
    ws = math.acos(-math.tan(lat_rad) * math.tan(decl))

    ra = (24 * 60 / math.pi) * 0.0820 * dr * (
        ws * math.sin(lat_rad) * math.sin(decl)
        + math.cos(lat_rad) * math.cos(decl) * math.sin(ws)
    )
    rso = (0.75 + 2e-5 * elevation) * ra

    # --- Nettostrahlung ---
    rns = (1 - albedo) * rs

    es_tmax = 0.6108 * math.exp(17.27 * tmax / (tmax + 237.3))
    es_tmin = 0.6108 * math.exp(17.27 * tmin / (tmin + 237.3))
    es = (es_tmax + es_tmin) / 2
    ea = es * rh_mean / 100

    sigma = 4.903e-9  # Stefan-Boltzmann, MJ K^-4 m^-2 Tag^-1
    rnl = (
        sigma
        * (((tmax + 273.16) ** 4 + (tmin + 273.16) ** 4) / 2)
        * (0.34 - 0.14 * math.sqrt(ea))
        * (1.35 * (rs / rso) - 0.35)
    )
    rn = rns - rnl

    p = 101.3 * ((293 - 0.0065 * elevation) / 293) ** 5.26
    gamma = 0.000665 * p

    delta = (
        4098
        * (0.6108 * math.exp(17.27 * tmean / (tmean + 237.3)))
        / (tmean + 237.3) ** 2
    )

    g = 0  # Bodenwärmestrom, für Tageswerte vernachlässigbar
    et0 = (
        0.408 * delta * (rn - g)
        + gamma * (900 / (tmean + 273)) * u2 * (es - ea)
    ) / (delta + gamma * (1 + 0.34 * u2))

    return {
        "et0": round(max(et0, 0), 2),
        "rs": round(rs, 2),
        "rs_poa": round(rs_poa, 2),
        "transposition_factor": round(transposition_factor, 3),
        "rn": round(rn, 2),
        "tmean": round(tmean, 1),
        "u2": round(u2, 2),
        "es": round(es, 3),
        "ea": round(ea, 3),
    }


def calculate_etc(et0: float, kc: float) -> float:
    """Tatsächlicher Wasserbedarf einer Zone: ETc = ET0 x Kc (FAO-56)."""
    return round(max(et0, 0) * kc, 2)
