import yaml
from pathlib import Path

def load_config(path: str) -> dict:
    with open(Path(path), "r") as f:
        cfg = yaml.safe_load(f)
    # minimal validation
    assert "mqtt" in cfg and "transports" in cfg and "routes" in cfg
    return cfg
