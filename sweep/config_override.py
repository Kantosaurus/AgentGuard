"""
AgentGuard — Config Override Utilities

Deep-merge dot-notation overrides into config dicts and flatten for logging.
"""

import copy


def override_config(base_config, overrides):
    """Deep-merge dot-notation overrides into a copy of base_config.

    Example:
        override_config(cfg, {"model.d_model": 256, "training.lr": 1e-3})
        → sets cfg["model"]["d_model"] = 256, cfg["training"]["lr"] = 1e-3
    """
    config = copy.deepcopy(base_config)
    for key, value in overrides.items():
        parts = key.split(".")
        d = config
        for part in parts[:-1]:
            if part not in d:
                d[part] = {}
            d = d[part]
        d[parts[-1]] = value
    return config


def config_to_flat_dict(config, prefix=""):
    """Flatten nested config dict to dot-notation keys for logging.

    Example:
        {"model": {"d_model": 128}} → {"model.d_model": 128}
    """
    flat = {}
    for key, value in config.items():
        full_key = f"{prefix}.{key}" if prefix else key
        if isinstance(value, dict):
            flat.update(config_to_flat_dict(value, full_key))
        elif not isinstance(value, list):
            flat[full_key] = value
    return flat
