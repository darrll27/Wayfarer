"""Runner to start router from config for development/testing.

This module is a convenience script to start the router in its own process using
configuration from `config/config.yaml`.
"""
import os
import yaml
from .router import Router, parse_udp_uri


def load_router_config(path: str):
    with open(path, "r") as fh:
        data = yaml.safe_load(fh) or {}
    return data.get("router", {})


def start_router_from_config(config_path=None):
    if config_path is None:
        config_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "config", "config.yaml"))
    rconf = load_router_config(config_path)
    bind_s = rconf.get("bind", "0.0.0.0:14540")
    targets_s = rconf.get("targets", [])
    bind = parse_udp_uri(bind_s)
    targets = [parse_udp_uri(t) for t in targets_s]
    r = Router(bind, targets)
    r.start()
    return r


if __name__ == "__main__":
    r = start_router_from_config()
    try:
        import time
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        r.stop()
