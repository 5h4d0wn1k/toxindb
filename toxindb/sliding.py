"""Sliding window utilities for temporal analysis."""
from __future__ import annotations

from typing import List, Tuple, Optional


def sliding_window(timestamps: List[float], window_sec: float, step_sec: Optional[float] = None) -> List[Tuple[float, float, int]]:
    if not timestamps:
        return []
    if step_sec is None:
        step_sec = window_sec / 2.0
    start = min(timestamps)
    end = max(timestamps)
    windows = []
    t = start
    while t <= end + 1e-9:
        w_end = t + window_sec
        count = sum(1 for ts in timestamps if ts >= t - 1e-9 and ts < w_end + 1e-9)
        windows.append((t, w_end, count))
        t += step_sec
    return windows
