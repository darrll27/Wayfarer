import yaml
from pathlib import Path
from .broker import load_common_mqtt_defaults

def load_config(path: str) -> dict:
    with open(Path(path), "r") as f:
        cfg = yaml.safe_load(f)
    # minimal validation
    # Fill mqtt defaults if missing or partial using Houston configs
    if "mqtt" not in cfg or not isinstance(cfg.get("mqtt"), dict):
        cfg["mqtt"] = {}
    defaults = load_common_mqtt_defaults(Path(path).parent)
    cfg["mqtt"].setdefault("host", defaults.get("host"))
    cfg["mqtt"].setdefault("port", defaults.get("port"))
    cfg["mqtt"].setdefault("topic_prefix", defaults.get("topic_prefix"))
    cfg["mqtt"].setdefault("qos", defaults.get("qos", 0))

    assert "mqtt" in cfg and "transports" in cfg and "routes" in cfg
    return cfg
