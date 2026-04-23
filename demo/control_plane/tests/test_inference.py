"""Scorer integration test — loads the actual checkpoint and runs a forward
pass. Marked ``slow`` because it boots the full AgentGuardModel; skip with
``-m "not slow"`` in fast CI passes."""
from __future__ import annotations

import os

import numpy as np
import pytest

from app.config import Config


@pytest.mark.slow
def test_scorer_runs_strict_true():
    cfg = Config()
    if not os.path.exists(cfg.checkpoint_path):
        pytest.skip(f"checkpoint not present at {cfg.checkpoint_path}")
    if not os.path.exists(cfg.config_yaml):
        pytest.skip(f"config.yml not present at {cfg.config_yaml}")

    # Imported here so the skip fires before we try to load torch+mamba.
    from app.inference import Scorer

    mean = np.zeros(32, dtype=np.float32)
    std = np.ones(32, dtype=np.float32)
    scorer = Scorer(cfg, mean, std, strict_load=True)

    score = scorer.score(
        np.zeros((8, 32), dtype=np.float32),
        np.zeros((64, 28), dtype=np.float32),
        np.zeros(64, dtype=bool),
    )
    assert 0.0 <= score <= 1.0


@pytest.mark.slow
def test_scorer_normalizes_stream1():
    """Different Stream 1 inputs should yield different scores (normalization
    actually gets applied and the model sees distinct signal)."""
    cfg = Config()
    if not os.path.exists(cfg.checkpoint_path):
        pytest.skip(f"checkpoint not present at {cfg.checkpoint_path}")

    from app.inference import Scorer

    mean = np.zeros(32, dtype=np.float32)
    std = np.ones(32, dtype=np.float32)
    scorer = Scorer(cfg, mean, std, strict_load=True)

    s2 = np.zeros((64, 28), dtype=np.float32)
    mask = np.zeros(64, dtype=bool)

    s_zero = scorer.score(np.zeros((8, 32), dtype=np.float32), s2, mask)
    s_one = scorer.score(np.ones((8, 32), dtype=np.float32) * 3.0, s2, mask)

    assert 0.0 <= s_zero <= 1.0
    assert 0.0 <= s_one <= 1.0
    # They don't have to differ by much, but a real forward with distinct
    # inputs and a trained model should not produce identical floats.
    assert s_zero != s_one
