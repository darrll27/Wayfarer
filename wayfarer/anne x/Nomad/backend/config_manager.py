"""Simple config helper for Nomad backend.

Reads `config/Config.yaml` if present, otherwise falls back to defaults.

Used by the CLI to find the MQTT broker and default src sysid/compid.
"""
from pathlib import Path
import yaml

DEFAULTS = {
    "mqtt": {
        "host": "localhost",
        "port": 1883,
        "username": None,
        "password": None,
        "keepalive": 60,
    },
    "gcs_sysid": 250,
    "gcs_compid": 1,
}


def load_config(repo_root: Path = None) -> dict:
    """Load configuration file from repo_root/config.

    Accepts either `Config.yaml` or `config.yaml` (case-insensitive) to be
    tolerant of different naming. Returns a dict merging DEFAULTS with the
    loaded values. Keys merged: mqtt, transports, endpoints, groups, forwards,
    gcs_sysid, gcs_compid.
    """
    # assume repo root is one level up from this file (backend/..)
    repo_root = repo_root or Path(__file__).resolve().parents[1]
    cfg_dir = repo_root / "config"
    cfg_path = cfg_dir / "config.yaml"

    if not cfg_path.exists():
        raise FileNotFoundError(f"Configuration file not found at expected path: {cfg_path}")

    # load user config strictly (no fallback behavior)
    with cfg_path.open("r") as f:
        user_cfg = yaml.safe_load(f) or {}

    # start from DEFAULTS but prefer values from user_cfg; do NOT silently ignore missing config
    cfg = DEFAULTS.copy()
    # ensure collection keys exist
    cfg["transports"] = user_cfg.get("transports", [])
    cfg["endpoints"] = user_cfg.get("endpoints", {})
    cfg["groups"] = user_cfg.get("groups", {})
    cfg["forwards"] = user_cfg.get("forwards", [])

    # merge mqtt explicitly
    mqtt = user_cfg.get("mqtt", {})
    cfg["mqtt"] = {**cfg["mqtt"], **(mqtt or {})}

    # scalar overrides
    if "gcs_sysid" in user_cfg:
        cfg["gcs_sysid"] = user_cfg["gcs_sysid"]
    if "gcs_compid" in user_cfg:
        cfg["gcs_compid"] = user_cfg["gcs_compid"]

    # propagate verbose flag if set
    cfg["verbose"] = user_cfg.get("verbose", False)

    return cfg


def parse_endpoint_uri(uri: str) -> dict:
    """Parse a simple endpoint URI like udp://host:port and return dict with type/host/port.

    Returns None if parsing fails.
    """
    if not uri or not isinstance(uri, str):
        return None
    uri = uri.strip()
    if uri.startswith("udp://"):
        rest = uri[len("udp://") :]
        if ":" in rest:
            host, port = rest.split(":", 1)
            try:
                return {"type": "udp", "host": host, "port": int(port)}
            except Exception:
                return None
    # add other schemes later (serial://...) if needed
    return None


def resolve_endpoint(name: str, cfg: dict) -> dict:
    """Resolve an endpoint name from cfg['endpoints'] to a parsed dict.

    Example return: { 'type': 'udp', 'host': '127.0.0.1', 'port': 14560 }
    Returns None if not resolvable.
    """
    if not name or not cfg:
        return None
    endpoints = cfg.get("endpoints", {}) or {}
    uri = endpoints.get(name)
    if uri is None:
        return None
    return parse_endpoint_uri(uri)


if __name__ == "__main__":
    import json
    print(json.dumps(load_config(), indent=2))
