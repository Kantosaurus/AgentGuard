"""Markdown detection report rendering for a single sample.

Composes attribution heatmaps (Stream 1 + Stream 2) as a PNG and returns a
markdown string referencing that PNG plus tables for top flagged action pairs
and top feature deviations.
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Tuple, Union

import matplotlib

# Use a non-interactive backend to keep the driver headless-safe.
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import torch

from .feature_deviation import FEATURE_NAMES


def _as_numpy(x) -> np.ndarray:
    if isinstance(x, torch.Tensor):
        return x.detach().cpu().numpy()
    return np.asarray(x)


def _abbrev_feature_names(names: List[str], max_len: int = 12) -> List[str]:
    """Abbreviate feature names for compact x-axis labels."""
    out = []
    for name in names:
        if len(name) > max_len:
            out.append(name[: max_len - 1] + ".")
        else:
            out.append(name)
    return out


def _render_heatmap_png(
    stream1_attr: np.ndarray,
    stream2_attr: np.ndarray,
    png_path: Path,
    title: str,
) -> None:
    """Render the 2-panel attribution heatmap to ``png_path``."""
    stream1_attr = _as_numpy(stream1_attr)
    stream2_attr = _as_numpy(stream2_attr)

    # Color scale: symmetric around 0, use global max abs across both panels
    # so the two heatmaps share a meaningful magnitude comparison.
    vmax = max(
        float(np.abs(stream1_attr).max()) if stream1_attr.size else 0.0,
        float(np.abs(stream2_attr).max()) if stream2_attr.size else 0.0,
        1e-12,
    )

    fig, (ax_top, ax_bot) = plt.subplots(
        2, 1, figsize=(12, 9),
        gridspec_kw={"height_ratios": [1, 2]},
    )

    im_top = ax_top.imshow(
        stream1_attr, aspect="auto", cmap="coolwarm",
        vmin=-vmax, vmax=vmax, interpolation="nearest",
    )
    ax_top.set_title("Stream 1 attribution (telemetry context x feature)")
    ax_top.set_xlabel("feature")
    ax_top.set_ylabel("context step")
    ax_top.set_xticks(range(stream1_attr.shape[1]))
    ax_top.set_xticklabels(
        _abbrev_feature_names(FEATURE_NAMES),
        rotation=75, fontsize=7,
    )
    ax_top.set_yticks(range(stream1_attr.shape[0]))
    fig.colorbar(im_top, ax=ax_top, fraction=0.02, pad=0.02)

    im_bot = ax_bot.imshow(
        stream2_attr, aspect="auto", cmap="coolwarm",
        vmin=-vmax, vmax=vmax, interpolation="nearest",
    )
    ax_bot.set_title("Stream 2 attribution (action position x feature)")
    ax_bot.set_xlabel("feature dim (0-4 event, 5-20 tool, 21-27 scalar/flag)")
    ax_bot.set_ylabel("action position")
    ax_bot.set_xticks(range(0, stream2_attr.shape[1]))
    ax_bot.set_xticklabels(range(stream2_attr.shape[1]), fontsize=7)
    fig.colorbar(im_bot, ax=ax_bot, fraction=0.02, pad=0.02)

    fig.suptitle(title, fontsize=11)
    fig.tight_layout(rect=[0, 0, 1, 0.97])

    png_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(png_path, dpi=120)
    plt.close(fig)


def render_report(
    sample_meta: Dict,
    temporal_attr: Dict,
    action_pairs: List[Dict],
    feature_zscores: Dict,
    figure_dir: Union[str, Path],
) -> str:
    """Render a per-sample markdown detection report.

    Writes the attribution heatmap PNG next to the returned markdown. The
    caller is responsible for writing the markdown to disk.

    Args:
        sample_meta: ``{agent_id, window_idx, attack_id, attack_category,
            y_true, y_score}``.
        temporal_attr: dict from ``attribute_temporal``.
        action_pairs:  list from ``flag_action_pairs`` (already top-k).
        feature_zscores: dict from ``feature_zscores`` (caller passes whichever
            top_k slice it wants — usually the first 5 entries).
        figure_dir: directory to drop the heatmap PNG into.

    Returns:
        Markdown string. The PNG is written as
        ``{figure_dir}/{agent_id}_{window_idx}_attr.png`` and referenced via a
        relative link so the .md can live next to the PNG.
    """
    figure_dir = Path(figure_dir)
    agent_id = sample_meta["agent_id"]
    window_idx = int(sample_meta["window_idx"])
    attack_id = sample_meta.get("attack_id", "") or ""
    attack_category = sample_meta.get("attack_category", "") or ""
    y_true = int(sample_meta.get("y_true", 0))
    y_score = float(sample_meta.get("y_score", 0.0))

    png_filename = f"{agent_id}_{window_idx}_attr.png"
    png_path = figure_dir / png_filename

    title = (
        f"{agent_id} window {window_idx} - "
        f"score={y_score:.4f} label={y_true}"
    )
    _render_heatmap_png(
        temporal_attr["stream1_attr"],
        temporal_attr["stream2_attr"],
        png_path,
        title=title,
    )

    lines: List[str] = []
    lines.append(f"# Detection report: {agent_id} window {window_idx}")
    lines.append("")
    lines.append(
        f"- Attack id: `{attack_id}` ({attack_category})"
        if attack_id else f"- Attack id: `` ({attack_category})"
    )
    lines.append(f"- Ground-truth label: {y_true}")
    lines.append(f"- Model score: {y_score:.4f}")
    lines.append("")

    lines.append("## Temporal attribution")
    lines.append("")
    lines.append(f"![attribution](./{png_filename})")
    lines.append("")

    lines.append("## Top flagged action pairs")
    lines.append("")
    if action_pairs:
        lines.append("| rank | position | magnitude | event types | tools |")
        lines.append("|------|----------|-----------|-------------|-------|")
        for rank, pair in enumerate(action_pairs, start=1):
            e1, e2 = pair["event_types"]
            t1, t2 = pair["tools"]
            e_cell = f"{e1 or '-'} -> {e2 or '-'}"
            t_cell = f"{t1 or '-'} -> {t2 or '-'}"
            lines.append(
                f"| {rank} | {pair['position']} | {pair['magnitude']:.4f} "
                f"| {e_cell} | {t_cell} |"
            )
    else:
        lines.append("_No adjacent action pairs observed in this window._")
    lines.append("")

    lines.append("## Top feature deviations")
    lines.append("")
    top = feature_zscores.get("top_k", [])
    if top:
        lines.append("| rank | feature | z-score | sample | baseline mean |")
        lines.append("|------|---------|---------|--------|---------------|")
        for rank, entry in enumerate(top, start=1):
            name, z, val, mean = entry
            lines.append(
                f"| {rank} | {name} | {z:.2f} | {val:.4f} | {mean:.4f} |"
            )
    else:
        lines.append("_No feature deviations available._")
    lines.append("")

    return "\n".join(lines)
