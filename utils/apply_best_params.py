import json
import yaml
import copy

if __name__ == "__main__":
    # 1. Load base config
    with open("config.yml") as f:
        base_config = yaml.safe_load(f)

    # 2. Load & merge all phases
    paths = [
        "sweep/results/best_params_phase1.json",
        "sweep/results/best_params_phase2.json",
        "sweep/results/best_params_phase3.json",
        "sweep/results/best_params_phase4.json",
    ]

    best_params = {}
    for path in paths:
        with open(path) as f:
            best_params.update(json.load(f))

    # 3. Apply updates
    new_config = copy.deepcopy(base_config)

    for key, value in best_params.items():
        if key in new_config["model"]:
            new_config["model"][key] = value
        elif key in new_config["training"]:
            new_config["training"][key] = value
        elif key in new_config["data"]:
            new_config["data"][key] = value
        else:
            print(f"[WARNING] Unknown key: {key}")

    # 4. Save updated config
    with open("config_best.yml", "w") as f:
        yaml.safe_dump(new_config, f)

    print("Config overridden and saved to config_best.yml")