"""Data models for trail kinematics."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class BodyTrailKinematics:
    hue_list: list[float]
    segment_colors: list[tuple[int, int, int]]


@dataclass(frozen=True)
class TrailKinematicsBundle:
    by_body: dict[str, BodyTrailKinematics]
    global_speed_max: float
    global_angular_speed_max: float
    global_accel_max: float


@dataclass(frozen=True)
class RawBodyKinematics:
    hues: list[float]
    speeds: list[float]
    angular_speeds: list[float]
    accels: list[float]


@dataclass(frozen=True)
class KinematicsGeometry:
    image_width: int
    image_height: int


@dataclass(frozen=True)
class TrailColorPolicy:
    fade_power: float
    min_fade: float
    dynamic_saturation: bool
    saturation_angular_blend: float
    brightness_angular_blend: float


@dataclass(frozen=True)
class KinematicsRuntime:
    body_names: tuple[str, ...]
    center_name: str
    body_brightness: dict[str, float]


@dataclass(frozen=True)
class GlobalMetricMaxima:
    speed: float
    angular_speed: float
    accel: float
