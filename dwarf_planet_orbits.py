"""Analytic dwarf-planet orbital model used as an ephemeris fallback."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import math

import numpy as np


J2000 = datetime(2000, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
GAUSSIAN_GRAVITATIONAL_CONSTANT = 0.01720209895


@dataclass(frozen=True)
class OrbitalElements:
    semi_major_axis_au: float
    eccentricity: float
    inclination_deg: float
    ascending_node_deg: float
    argument_of_perihelion_deg: float
    mean_anomaly_deg: float
    epoch: datetime = J2000


DWARF_PLANET_ORBITS: dict[str, OrbitalElements] = {
    "ceres": OrbitalElements(2.7675, 0.0785, 10.6, 80.3, 73.6, 291.4, datetime(2022, 1, 21, tzinfo=timezone.utc)),
    "pluto": OrbitalElements(39.482, 0.2488, 17.16, 110.299, 113.834, 14.53),
    "eris": OrbitalElements(67.69, 0.44, 44.18, 36.02, 151.66, 205.11),
    "haumea": OrbitalElements(43.116, 0.19642, 28.2137, 122.167, 239.041, 218.205),
    "makemake": OrbitalElements(45.499, 0.1604, 29.002, 79.441, 296.065, 170.497),
    "gonggong": OrbitalElements(66.895, 0.50318, 30.8664, 336.8401, 206.6442, 111.384),
    "quaoar": OrbitalElements(43.694, 0.04106, 7.9895, 188.927, 147.480, 301.104),
}


def is_dwarf_planet_body(name: str) -> bool:
    return name.lower() in DWARF_PLANET_ORBITS


def _normalize_angle(angle_rad: float) -> float:
    return angle_rad % (2.0 * math.pi)


def _solve_kepler(mean_anomaly_rad: float, eccentricity: float) -> float:
    anomaly = mean_anomaly_rad if eccentricity < 0.8 else math.pi
    for _ in range(32):
        f = anomaly - eccentricity * math.sin(anomaly) - mean_anomaly_rad
        f_prime = 1.0 - eccentricity * math.cos(anomaly)
        delta = f / f_prime
        anomaly -= delta
        if abs(delta) < 1e-12:
            break
    return anomaly


def _heliocentric_position(elements: OrbitalElements, at_time: datetime) -> np.ndarray:
    utc_time = at_time if at_time.tzinfo is not None else at_time.replace(tzinfo=timezone.utc)
    utc_time = utc_time.astimezone(timezone.utc)
    epoch = elements.epoch if elements.epoch.tzinfo is not None else elements.epoch.replace(tzinfo=timezone.utc)
    epoch = epoch.astimezone(timezone.utc)

    delta_days = (utc_time - epoch).total_seconds() / 86400.0
    mean_motion = GAUSSIAN_GRAVITATIONAL_CONSTANT / (elements.semi_major_axis_au ** 1.5)
    mean_anomaly = _normalize_angle(math.radians(elements.mean_anomaly_deg) + mean_motion * delta_days)
    eccentric_anomaly = _solve_kepler(mean_anomaly, elements.eccentricity)

    cos_e = math.cos(eccentric_anomaly)
    sin_e = math.sin(eccentric_anomaly)
    sqrt_one_minus_e2 = math.sqrt(max(0.0, 1.0 - elements.eccentricity**2))

    x_orb = elements.semi_major_axis_au * (cos_e - elements.eccentricity)
    y_orb = elements.semi_major_axis_au * sqrt_one_minus_e2 * sin_e

    omega = math.radians(elements.argument_of_perihelion_deg)
    inclination = math.radians(elements.inclination_deg)
    ascending_node = math.radians(elements.ascending_node_deg)

    cos_omega = math.cos(omega)
    sin_omega = math.sin(omega)
    cos_i = math.cos(inclination)
    sin_i = math.sin(inclination)
    cos_node = math.cos(ascending_node)
    sin_node = math.sin(ascending_node)

    x1 = x_orb * cos_omega - y_orb * sin_omega
    y1 = x_orb * sin_omega + y_orb * cos_omega

    x2 = x1
    y2 = y1 * cos_i
    z2 = y1 * sin_i

    x = x2 * cos_node - y2 * sin_node
    y = x2 * sin_node + y2 * cos_node
    z = z2

    return np.asarray([x, y, z], dtype=float)


def get_heliocentric_trail_vectors(name: str, datetimes: list[datetime]) -> list[np.ndarray]:
    elements = DWARF_PLANET_ORBITS[name.lower()]
    return [_heliocentric_position(elements, at_time) for at_time in datetimes]