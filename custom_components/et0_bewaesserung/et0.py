"""FAO-56 Penman-Monteith Berechnung (reine Funktion, keine HA-Abhängigkeiten)."""

from __future__ import annotations

import math
from datetime import date


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
) -> dict:
    """Berechnet ET0 (mm/Tag) und liefert Zwischenwerte zur Diagnose zurück."""

    calc_date = calc_date or date.today()
    tmean = (tmax + tmin) / 2
    u2 = wind_mean_kmh / 3.6 * 0.748  # km/h -> m/s, Höhenkorrektur 10m -> 2m

    # --- Rs aus PV-Ertrag ableiten (Näherung) ---
    h_poa_kwh_m2 = pv_yield_kwh / (kwp * performance_ratio)
    rs = h_poa_kwh_m2 * 3.6  # kWh/m2 -> MJ/m2/Tag

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
        "rn": round(rn, 2),
        "tmean": round(tmean, 1),
        "u2": round(u2, 2),
        "es": round(es, 3),
        "ea": round(ea, 3),
    }


def calculate_etc(et0: float, kc: float) -> float:
    """Tatsächlicher Wasserbedarf einer Zone: ETc = ET0 x Kc (FAO-56)."""
    return round(max(et0, 0) * kc, 2)
