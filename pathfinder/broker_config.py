import os
import json
import yaml


def _read_json(path, fallback=None):
    try:
        with open(path, 'r') as f:
            return json.load(f)
    except Exception:
        return fallback


def _read_yaml(path, fallback=None):
    try:
        with open(path, 'r') as f:
            return yaml.safe_load(f)
    except Exception:
        return fallback


def find_repo_root(start_dir):
    d = os.path.abspath(start_dir)
    while True:
        if os.path.isdir(os.path.join(d, '.git')):
            return d
        parent = os.path.dirname(d)
        if parent == d:
            return os.path.abspath(start_dir)
        d = parent


def load_houston_broker_and_ui_cfg(base_dir):
    """Locate Houston config files and load them if present.
    Returns (broker_cfg, houston_cfg) where both are dict or None.
    """
    root = find_repo_root(base_dir)
    h_dir = os.path.join(root, 'Houston', 'config')
    broker_path = os.path.join(h_dir, 'broker.config.json')
    houston_path = os.path.join(h_dir, 'houston.config.json')
    broker = _read_json(broker_path, {}) if os.path.exists(broker_path) else {}
    houston = _read_json(houston_path, {}) if os.path.exists(houston_path) else {}
    return broker or None, houston or None


def load_common_mqtt_cfg(base_dir, override_cfg=None):
    """Build a common MQTT client config by merging:
    1) override_cfg (from pathfinder.config.yaml 'mqtt')
    2) Houston broker + UI configs (tcp_port, topic_prefix)
    3) Environment variables (HOUSTON_MQTT_HOST, HOUSTON_MQTT_PORT, HOUSTON_TOPIC_PREFIX)
    4) Sensible defaults

    Returns dict with keys: host, port, client_id, topic_prefix, qos, username?, password?
    """
    override_cfg = override_cfg or {}

    broker_cfg, ui_cfg = load_houston_broker_and_ui_cfg(base_dir)

    env_host = os.getenv('HOUSTON_MQTT_HOST')
    env_port = os.getenv('HOUSTON_MQTT_PORT')
    env_prefix = os.getenv('HOUSTON_TOPIC_PREFIX')

    host = (
        override_cfg.get('host')
        or (broker_cfg or {}).get('host')
        or 'localhost'
    )
    try:
        port = int(
            override_cfg.get('port')
            or (broker_cfg or {}).get('tcp_port')
            or 1883
        )
    except Exception:
        port = 1883

    topic_prefix = (
        override_cfg.get('topic_prefix')
        or (ui_cfg or {}).get('topic_prefix')
        or 'wayfarer/v1'
    )

    # env overrides last
    if env_host:
        host = env_host
    if env_port:
        try:
            port = int(env_port)
        except Exception:
            pass
    if env_prefix:
        topic_prefix = env_prefix

    out = {
        'host': host,
        'port': port,
        'client_id': override_cfg.get('client_id') or 'pathfinder-controller',
        'topic_prefix': topic_prefix,
        'qos': int(override_cfg.get('qos', 0)),
    }

    # optional auth
    if 'username' in (override_cfg or {}):
        out['username'] = override_cfg.get('username')
    if 'password' in (override_cfg or {}):
        out['password'] = override_cfg.get('password')

    return out
