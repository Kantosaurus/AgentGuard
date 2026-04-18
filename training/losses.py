"""
AgentGuard — Hybrid Loss Functions

Three-part loss: L = λ1·L_recon + λ2·L_contrastive + λ3·L_temporal

- L_recon:       MSE reconstruction loss for both streams
- L_contrastive: Supervised contrastive loss on latent embeddings
- L_temporal:    Temporal smoothness penalty on adjacent window latents
"""

import torch
import torch.nn as nn
import torch.nn.functional as F


class ReconstructionLoss(nn.Module):
    """Combined MSE reconstruction loss for Stream 1 and Stream 2.

    Stream 1: MSE between reconstructed and original last-window telemetry.
    Stream 2: Masked MSE — only compute loss on real (non-padding) positions.
    """

    def forward(self, stream1_recon, stream1_target, stream2_recon, stream2_target, stream2_mask):
        """
        Args:
            stream1_recon:  [B, 32]
            stream1_target: [B, 32] — last window of input sequence
            stream2_recon:  [B, 64, 28]
            stream2_target: [B, 64, 28]
            stream2_mask:   [B, 64] — 1 for real events, 0 for padding
        """
        # Stream 1 MSE
        loss_s1 = F.mse_loss(stream1_recon, stream1_target)

        # Stream 2 masked MSE
        mask = stream2_mask.unsqueeze(-1)  # [B, 64, 1]
        diff = (stream2_recon - stream2_target) ** 2  # [B, 64, 28]
        masked_diff = diff * mask
        num_elements = mask.sum().clamp(min=1) * stream2_target.size(-1)
        loss_s2 = masked_diff.sum() / num_elements

        return loss_s1 + loss_s2


class SupervisedContrastiveLoss(nn.Module):
    """Supervised contrastive loss (SupCon) on latent embeddings.

    Same-class samples are pulled together, different-class samples pushed apart.
    Based on: Khosla et al., "Supervised Contrastive Learning" (2020).
    """

    def __init__(self, temperature=0.07, class_weight_ratio=1.0):
        super().__init__()
        self.temperature = temperature
        self.class_weight_ratio = class_weight_ratio

    def forward(self, latents, labels):
        """
        Args:
            latents: [B, latent_dim] — L2-normalized latent embeddings
            labels:  [B] — binary labels (0 or 1)
        Returns:
            scalar contrastive loss
        """
        device = latents.device
        batch_size = latents.size(0)

        if batch_size <= 1:
            return torch.tensor(0.0, device=device)

        # L2 normalize
        latents = F.normalize(latents, dim=1)

        # Similarity matrix
        sim = torch.mm(latents, latents.t()) / self.temperature  # [B, B]

        # Mask: same class pairs (excluding self)
        labels = labels.view(-1, 1)
        mask_pos = (labels == labels.t()).float()  # [B, B]
        mask_self = torch.eye(batch_size, device=device)
        mask_pos = mask_pos - mask_self  # exclude self-similarity

        # Number of positive pairs per sample
        num_pos = mask_pos.sum(dim=1)

        # If any sample has no positive pair, skip those
        valid = num_pos > 0
        if valid.sum() == 0:
            return torch.tensor(0.0, device=device)

        # Log-softmax: subtract max for numerical stability
        logits_max, _ = sim.max(dim=1, keepdim=True)
        logits = sim - logits_max.detach()

        # Exclude self from denominator
        exp_logits = torch.exp(logits) * (1 - mask_self)
        log_prob = logits - torch.log(exp_logits.sum(dim=1, keepdim=True).clamp(min=1e-8))

        # Mean log-probability over positive pairs
        mean_log_prob = (mask_pos * log_prob).sum(dim=1) / num_pos.clamp(min=1)

        # Per-sample weighting: up-weight anomalous class (label=1)
        if self.class_weight_ratio != 1.0:
            weights = torch.where(
                labels.squeeze() == 1,
                torch.tensor(self.class_weight_ratio, device=device),
                torch.tensor(1.0, device=device),
            )
            loss = -(mean_log_prob[valid] * weights[valid]).sum() / weights[valid].sum()
        else:
            loss = -mean_log_prob[valid].mean()
        return loss


class TemporalSmoothnessLoss(nn.Module):
    """Penalizes large latent-space jumps between adjacent windows of the same agent.

    Checks window_idx[i+1] - window_idx[i] == 1 to verify true adjacency
    within the same agent's timeline.
    """

    def forward(self, latents, window_indices, agent_indices):
        """
        Args:
            latents:        [B, latent_dim]
            window_indices: [B] — window position in agent timeline
            agent_indices:  [B] — agent index (ensures same-agent adjacency)
        Returns:
            scalar temporal smoothness loss
        """
        if latents.size(0) <= 1:
            return torch.tensor(0.0, device=latents.device)

        # Find adjacent pairs: same agent AND window_idx differs by exactly 1
        same_agent = (agent_indices[1:] == agent_indices[:-1])
        diffs = window_indices[1:] - window_indices[:-1]
        adjacent_mask = same_agent & (diffs == 1)

        if adjacent_mask.sum() == 0:
            return torch.tensor(0.0, device=latents.device)

        # L2 distance between adjacent latents
        latent_diffs = (latents[1:] - latents[:-1]) ** 2
        latent_dists = latent_diffs.sum(dim=1)  # [B-1]

        # Only penalize truly adjacent windows from the same agent
        loss = latent_dists[adjacent_mask].mean()
        return loss


class HybridLoss(nn.Module):
    """Combined four-part loss for AgentGuard training.

    L = λ_recon·L_recon + λ_contrastive·L_contrastive + λ_temporal·L_temporal
        + λ_cls·L_cls

    L_cls is a weighted binary cross-entropy on the anomaly_head output; it
    anchors the head's polarity so sigmoid(head) actually represents an
    anomaly probability instead of an arbitrary scalar shaped only by the
    contrastive latent geometry.
    """

    def __init__(self, lambda_recon=1.0, lambda_contrastive=0.5, lambda_temporal=0.1,
                 lambda_cls=1.0, class_weight_ratio=1.0):
        super().__init__()
        self.lambda_recon = lambda_recon
        self.lambda_contrastive = lambda_contrastive
        self.lambda_temporal = lambda_temporal
        self.lambda_cls = lambda_cls
        self.class_weight_ratio = class_weight_ratio

        self.recon_loss = ReconstructionLoss()
        self.contrastive_loss = SupervisedContrastiveLoss(class_weight_ratio=class_weight_ratio)
        self.temporal_loss = TemporalSmoothnessLoss()

    _warned_nan_scores = False

    def _classification_loss(self, scores, labels):
        scores = scores.squeeze(-1)
        # Guard against NaN/Inf from the anomaly head. These can appear on
        # Hopper (H100/H200) when the SSM prefix-scan overflows before
        # reaching sigmoid; unprotected, BCELoss fires a device-side
        # assertion and kills the whole process.
        bad = ~torch.isfinite(scores)
        if bad.any():
            if not HybridLoss._warned_nan_scores:
                print(
                    f"[losses] warning: non-finite anomaly_score "
                    f"({bad.sum().item()}/{bad.numel()} elems); "
                    f"replacing with 0.5 so BCE can proceed",
                    flush=True,
                )
                HybridLoss._warned_nan_scores = True
            scores = torch.where(bad, torch.full_like(scores, 0.5), scores)
        scores = scores.clamp(1e-7, 1.0 - 1e-7)
        labels = labels.float()
        weights = torch.where(
            labels > 0.5,
            torch.tensor(self.class_weight_ratio, device=scores.device),
            torch.tensor(1.0, device=scores.device),
        )
        return F.binary_cross_entropy(scores, labels, weight=weights)

    def forward(self, outputs, batch):
        """
        Args:
            outputs: dict from AgentGuardModel.forward()
            batch:   dict from DataLoader (collated)
        Returns:
            (total_loss, loss_dict) where loss_dict has individual components
        """
        # Reconstruction targets
        stream1_target = batch["stream1"][:, -1, :]  # last window [B, 32]
        stream2_target = batch["stream2_seq"]         # [B, 64, 28]
        stream2_mask = batch["stream2_mask"]           # [B, 64]

        l_recon = self.recon_loss(
            outputs["stream1_recon"], stream1_target,
            outputs["stream2_recon"], stream2_target,
            stream2_mask,
        )

        l_contrastive = self.contrastive_loss(
            outputs["latent"], batch["label"],
        )

        l_temporal = self.temporal_loss(
            outputs["latent"], batch["window_idx"], batch["agent_idx"],
        )

        l_cls = self._classification_loss(outputs["anomaly_score"], batch["label"])

        total = (self.lambda_recon * l_recon
                 + self.lambda_contrastive * l_contrastive
                 + self.lambda_temporal * l_temporal
                 + self.lambda_cls * l_cls)

        return total, {
            "recon": l_recon.item(),
            "contrastive": l_contrastive.item(),
            "temporal": l_temporal.item(),
            "cls": l_cls.item(),
            "total": total.item(),
        }
