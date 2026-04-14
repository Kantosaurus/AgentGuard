"""Per-sample interpretability utilities for AgentGuard.

Exposes:
    attribute_temporal   — Integrated Gradients over Stream 1 / Stream 2.
    flag_action_pairs    — gradient-ranked adjacent action-pair scoring.
    compute_benign_baseline / feature_zscores — per-agent z-score deviations.
    render_report        — compose a markdown per-sample detection report.
"""

from .temporal_attribution import attribute_temporal
from .action_pair_flagging import flag_action_pairs
from .feature_deviation import (
    compute_benign_baseline,
    feature_zscores,
    FEATURE_NAMES,
)
from .report import render_report

__all__ = [
    "attribute_temporal",
    "flag_action_pairs",
    "compute_benign_baseline",
    "feature_zscores",
    "FEATURE_NAMES",
    "render_report",
]
