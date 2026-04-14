"""
AgentGuard — Hyperparameter Search Spaces

Three-phase search: architecture → training dynamics → loss & data.
Each function takes an Optuna trial and returns a dict of config overrides.
"""


def suggest_phase1_architecture(trial):
    """Phase 1: Architecture search."""
    d_model = trial.suggest_categorical("d_model", [64, 128, 256, 512])
    latent_dim = trial.suggest_categorical("latent_dim", [64, 128, 256])
    mamba_layers = trial.suggest_categorical("mamba_layers", [1, 2, 3, 4, 6])
    transformer_layers = trial.suggest_categorical("transformer_layers", [1, 2, 3, 4, 6])

    # Only allow heads that divide d_model evenly
    valid_heads = [h for h in [2, 4, 8] if d_model % h == 0]
    transformer_heads = trial.suggest_categorical("transformer_heads", valid_heads)

    transformer_ff_dim = trial.suggest_categorical("transformer_ff_dim", [256, 512, 1024])
    dropout = trial.suggest_categorical("dropout", [0.0, 0.05, 0.1, 0.2, 0.3])
    fusion_strategy = trial.suggest_categorical(
        "fusion_strategy", ["cross_attention", "concat_mlp", "gated", "attention_pool"]
    )
    cls_head_layers = trial.suggest_categorical("cls_head_layers", [1, 2, 3])
    cls_head_hidden_dim = trial.suggest_categorical("cls_head_hidden_dim", [32, 64, 128, 256])
    cls_head_activation = trial.suggest_categorical("cls_head_activation", ["relu", "gelu", "silu"])
    decoder_activation = trial.suggest_categorical("decoder_activation", ["relu", "gelu", "silu"])

    return {
        "model.d_model": d_model,
        "model.latent_dim": latent_dim,
        "model.mamba_layers": mamba_layers,
        "model.transformer_layers": transformer_layers,
        "model.transformer_heads": transformer_heads,
        "model.transformer_ff_dim": transformer_ff_dim,
        "model.dropout": dropout,
        "model.fusion_strategy": fusion_strategy,
        "model.cls_head_layers": cls_head_layers,
        "model.cls_head_hidden_dim": cls_head_hidden_dim,
        "model.cls_head_activation": cls_head_activation,
        "model.decoder_activation": decoder_activation,
    }


def suggest_phase2_training(trial, best_arch):
    """Phase 2: Training dynamics search. Locks architecture from best_arch."""
    overrides = dict(best_arch)

    lr = trial.suggest_float("lr", 1e-4, 3e-3, log=True)
    optimizer = trial.suggest_categorical("optimizer", ["adam", "adamw"])
    scheduler = trial.suggest_categorical("scheduler", ["cosine", "plateau", "onecycle"])
    batch_size = trial.suggest_categorical("batch_size", [16, 32, 64, 128, 256, 512])
    grad_clip = trial.suggest_categorical("grad_clip", [0.5, 1.0, 2.0, 5.0])

    overrides.update({
        "training.lr": lr,
        "training.optimizer": optimizer,
        "training.scheduler": scheduler,
        "training.batch_size": batch_size,
        "training.max_grad_norm": grad_clip,
    })

    if optimizer == "adamw":
        weight_decay = trial.suggest_float("weight_decay", 1e-5, 1e-2, log=True)
        overrides["training.weight_decay"] = weight_decay

    return overrides


def suggest_phase3_loss_and_data(trial, best_arch_train):
    """Phase 3: Loss weights and data augmentation. Locks arch + training."""
    overrides = dict(best_arch_train)

    lambda_recon = trial.suggest_float("lambda_recon", 0.1, 2.0)
    lambda_contrastive = trial.suggest_float("lambda_contrastive", 0.1, 2.0)
    lambda_temporal = trial.suggest_float("lambda_temporal", 0.01, 0.5, log=True)
    seq_context = trial.suggest_categorical("seq_context", [4, 8, 16])
    augmentation = trial.suggest_categorical(
        "augmentation", ["none", "feature_mask", "time_jitter", "mixup"]
    )
    class_weight_ratio = trial.suggest_float("class_weight_ratio", 1.0, 5.0)

    overrides.update({
        "training.lambda_recon": lambda_recon,
        "training.lambda_contrastive": lambda_contrastive,
        "training.lambda_temporal": lambda_temporal,
        "data.seq_context": seq_context,
        "data.augmentation": augmentation,
        "data.class_weight_ratio": class_weight_ratio,
    })

    if augmentation != "none":
        aug_prob = trial.suggest_float("augmentation_prob", 0.1, 0.5)
        overrides["data.augmentation_prob"] = aug_prob

    return overrides
