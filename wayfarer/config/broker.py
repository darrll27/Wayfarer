import os
import json
import yaml
from pathlib import Path


def _read_json(path, fallback=None):
    try:
        with open(path, 'r') as f:
            return json.load(f)
    except Exception:
        return fallback


def find_repo_root(start_dir: Path) -> Path:
    d = start_dir.resolve()
    while True:
        if (d / '.git').is_dir():
            return d
        if d.parent == d:
            return start_dir.resolve()
        d = d.parent


def load_common_mqtt_defaults(start_dir: Path) -> dict:
    """Load default MQTT settings from Houston configs if present.
    Returns dict with host, port, topic_prefix, qos (no client_id).
    """
    root = find_repo_root(start_dir)
    h_cfg_dir = root / 'Houston' / 'config'
    broker_cfg = _read_json(str(h_cfg_dir / 'broker.config.json'), {}) if h_cfg_dir.exists() else {}
    ui_cfg = _read_json(str(h_cfg_dir / 'houston.config.json'), {}) if h_cfg_dir.exists() else {}

    host = broker_cfg.get('host') or 'localhost'
    port = int(broker_cfg.get('tcp_port') or 1883)
    topic_prefix = ui_cfg.get('topic_prefix') or 'wayfarer/v1'

    # env overrides
    host = os.getenv('HOUSTON_MQTT_HOST', host)
    try:
        port = int(os.getenv('HOUSTON_MQTT_PORT', port))
    except Exception:
        pass
    topic_prefix = os.getenv('HOUSTON_TOPIC_PREFIX', topic_prefix)

    return {
        'host': host,
        'port': port,
        'topic_prefix': topic_prefix,
        'qos': 0,
    }
