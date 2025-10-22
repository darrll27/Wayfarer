#!/usr/bin/env python3
"""
Simple, opinionated CLI for pathfinder.

Behavior:
- Uses `pathfinder/pathfinder.config.yaml` by default.
- If that config lacks an `mqtt` section, this CLI will inject sensible defaults
  (host/port/client_id/topic_prefix/qos) from this file and run using a
  temporary effective config.
- Runs missions by default when invoked with no args.
"""

import argparse
import os
import yaml
from pathlib import Path
from launch_missions import main as launch_main

ROOT = Path(__file__).resolve().parent
DEFAULT_CFG = ROOT / "pathfinder.config.yaml"

# Default MQTT settings embedded here (kept intentionally simple)
DEFAULT_MQTT = {
    "host": "localhost",
    "port": 1883,
    "client_id": "pathfinder-controller",
    "topic_prefix": "wayfarer/v1",
    "qos": 0,
}


def load_yaml(path):
    with open(path, "r") as fh:
        return yaml.safe_load(fh) or {}


def cli():
    p = argparse.ArgumentParser(prog="pathfinder", description="Pathfinder mission launcher CLI")
    p.add_argument("--config", "-c", help="Path to pathfinder config (overrides default)")
    p.add_argument("--run", action="store_true", help="Run missions now (otherwise prints effective config)")
    args = p.parse_args()

    # default to run when no args supplied
    import sys
    if len(sys.argv) == 1:
        args.run = True

    cfg_path = args.config or DEFAULT_CFG
    cfg = {}
    if os.path.exists(cfg_path):
        cfg = load_yaml(cfg_path) or {}

    # If mqtt is missing, merge defaults into an in-memory config and pass it
    # directly to the launcher. Do not write any file into the repo directory.
        tmp_path = None
        use_path = None
        if "mqtt" not in cfg or not isinstance(cfg.get("mqtt"), dict):
            # produce an in-memory effective config and write to a system temp file (do not write into the repo)
            effective = {**cfg, "mqtt": DEFAULT_MQTT}
            import tempfile
            fd, tmp = tempfile.mkstemp(prefix="pathfinder-effective-", suffix=".yaml")
            try:
                with os.fdopen(fd, "w") as fh:
                    yaml.safe_dump(effective, fh)
                tmp_path = tmp
                use_path = tmp_path
                print(f"Using defaults for mqtt from main.py (in-memory)")
            except Exception:
                # fallback to writing nothing and use original config path (best-effort)
                use_path = str(cfg_path)
                print(f"Using config: {use_path}")
        else:
            use_path = str(cfg_path)
            print(f"Using config: {use_path}")

    if args.run:
        # pass either a path or an in-memory dict to launch_missions.main
            try:
                launch_main(use_path)
            finally:
                if tmp_path:
                    try:
                        os.remove(tmp_path)
                    except Exception:
                        pass
    else:
        # Show the effective config
        try:
            cfg_to_show = load_yaml(use_path) if use_path and os.path.exists(use_path) else None
            if isinstance(cfg_to_show, dict):
                print("Effective config:\n")
                print(yaml.safe_dump(cfg_to_show, sort_keys=False))
            else:
                print(f"Effective config path: {use_path}")
        finally:
            if tmp_path:
                try:
                    os.remove(tmp_path)
                except Exception:
                    pass


if __name__ == "__main__":
    cli()
