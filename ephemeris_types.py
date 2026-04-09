"""Shared ephemeris data models."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class BodyState:
    position_au: np.ndarray
    trail_au: list[np.ndarray]
    trail_step_minutes: int
