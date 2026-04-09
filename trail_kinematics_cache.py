"""Persistence and signature helpers for trail kinematics raw data."""

from __future__ import annotations

import hashlib
import json
import os

from projection import ProjectedBody
from trail_kinematics_types import RawBodyKinematics


CACHE_VERSION = 4
CACHE_DIR = "trail_kinematics_cache"


def _safe_name(name: str) -> str:
    out = []
    for ch in name:
        if ch.isalnum() or ch in ("-", "_"):
            out.append(ch)
        else:
            out.append("_")
    return "".join(out)


def _body_cache_path(body_name: str, step_minutes: int) -> str:
    base = os.path.join(os.path.dirname(__file__), CACHE_DIR, f"step_{int(step_minutes)}")
    os.makedirs(base, exist_ok=True)
    return os.path.join(base, f"{_safe_name(body_name)}.json")


def body_signature(body: ProjectedBody) -> str:
    h = hashlib.sha256()
    trail = body.trail_au
    trail_xy = body.trail_xy
    n = len(trail)
    h.update(f"step:{body.trail_step_minutes};len:{n}|".encode("ascii"))
    if n:
        x0, y0, z0 = trail[0]
        x1, y1, z1 = trail[-1]
        h.update(f"f:{x0:.9f},{y0:.9f},{z0:.9f}|".encode("ascii"))
        h.update(f"l:{x1:.9f},{y1:.9f},{z1:.9f}|".encode("ascii"))
    if n > 2:
        xm, ym, zm = trail[n // 2]
        h.update(f"m:{xm:.9f},{ym:.9f},{zm:.9f}|".encode("ascii"))
    if trail_xy:
        x0, y0 = trail_xy[0]
        x1, y1 = trail_xy[-1]
        h.update(f"pf:{x0:.6f},{y0:.6f}|".encode("ascii"))
        h.update(f"pl:{x1:.6f},{y1:.6f}|".encode("ascii"))
    if len(trail_xy) > 2:
        xm, ym = trail_xy[len(trail_xy) // 2]
        h.update(f"pm:{xm:.6f},{ym:.6f}|".encode("ascii"))
    return h.hexdigest()


class RawKinematicsCache:
    def load(self, body_name: str, step_minutes: int, signature: str) -> RawBodyKinematics | None:
        path = _body_cache_path(body_name, step_minutes)
        if not os.path.exists(path):
            return None
        try:
            with open(path, "r", encoding="utf-8") as f:
                payload = json.load(f)
        except (OSError, json.JSONDecodeError):
            return None

        if payload.get("version") != CACHE_VERSION:
            return None
        if payload.get("signature") != signature:
            return None

        try:
            hues = [float(v) for v in payload.get("hues", [])]
            speeds = [float(v) for v in payload.get("speeds", [])]
            angular_speeds = [float(v) for v in payload.get("angular_speeds", [])]
            accels = [float(v) for v in payload.get("accels", [])]
        except (TypeError, ValueError):
            return None

        if not (len(hues) == len(speeds) == len(angular_speeds) == len(accels)):
            return None

        return RawBodyKinematics(hues=hues, speeds=speeds, angular_speeds=angular_speeds, accels=accels)

    def save(self, body_name: str, step_minutes: int, signature: str, raw: RawBodyKinematics) -> None:
        path = _body_cache_path(body_name, step_minutes)
        tmp = f"{path}.tmp"
        payload = {
            "version": CACHE_VERSION,
            "signature": signature,
            "hues": raw.hues,
            "speeds": raw.speeds,
            "angular_speeds": raw.angular_speeds,
            "accels": raw.accels,
        }
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(payload, f)
        os.replace(tmp, path)
