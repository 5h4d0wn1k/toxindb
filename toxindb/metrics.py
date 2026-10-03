"""Metrics and benchmark computation helpers."""
from __future__ import annotations

from typing import List, Tuple


def compute_metrics(tp: int, fp: int, tn: int, fn: int) -> Tuple[float, float, float, float, float]:
    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    tpr = recall
    fpr = fp / (fp + tn) if (fp + tn) > 0 else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0
    return tpr, fpr, precision, recall, f1
