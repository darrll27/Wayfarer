#!/usr/bin/env python3
"""Nomad backend CLI

Provides a small set of commands that map 1:1 to the app functionality so
you can troubleshoot backend behavior without the GUI.

Features implemented:
- publish MAVLink-like commands over MQTT to `command/<sysid>/<compid>/details`
- load a waypoint YAML and publish `command/<sysid>/<compid>/load_waypoints` with a file hash
- subscribe/listen to arbitrary MQTT topics (helpful for `device/...` or `sources/...`)

Usage examples (after activating venv and installing dependencies such as paho-mqtt and PyYAML):

  python backend/cli.py arm --target 3:1 --arm
  python backend/cli.py set-mode --target 3:1 --mode GUIDED
  python backend/cli.py get-mission --target 3:1
  python backend/cli.py load-waypoints --target 3:1 --file groups/teamA/waypoints.yaml
  python backend/cli.py listen --topic "device/+/+/HEARTBEAT/#"

The CLI publishes JSON payloads following the project's MQTT contract (see instructions.md).
"""
from __future__ import annotations

import argparse
import json
import hashlib
from pathlib import Path
import time
from typing import Any, Dict, List

import paho.mqtt.client as mqtt
import yaml

from .config_manager import load_config
from .mav_router import mission_test


def mqtt_client(cfg: dict) -> mqtt.Client:
    client = mqtt.Client()
    if cfg["mqtt"].get("username"):
        client.username_pw_set(cfg["mqtt"].get("username"), cfg["mqtt"].get("password"))
    client.connect(cfg["mqtt"]["host"], cfg["mqtt"]["port"], cfg["mqtt"].get("keepalive", 60))
    return client


def publish_command(client: mqtt.Client, target_sysid: int, target_compid: int, payload: Dict[str, Any]):
    topic = f"command/{target_sysid}/{target_compid}/details"
    client.loop_start()
    client.publish(topic, json.dumps(payload))
    # give broker a moment
    time.sleep(0.1)
    client.loop_stop()
    print(f"Published to {topic}: {json.dumps(payload)}")


def cmd_arm(args, cfg):
    client = mqtt_client(cfg)
    t_sys, t_comp = map(int, args.target.split(":"))
    arm_flag = 1 if args.arm else 0
    payload = {
        "command": "MAV_CMD_COMPONENT_ARM_DISARM",
        "params": [arm_flag, 0, 0, 0, 0, 0, 0],
        "src_sysid": cfg.get("gcs_sysid", 250),
        "src_compid": cfg.get("gcs_compid", 1),
    }
    publish_command(client, t_sys, t_comp, payload)


def cmd_set_mode(args, cfg):
    client = mqtt_client(cfg)
    t_sys, t_comp = map(int, args.target.split(":"))
    payload = {
        "command": "SET_MODE",
        "mode": args.mode,
        "params": [],
        "src_sysid": cfg.get("gcs_sysid", 250),
        "src_compid": cfg.get("gcs_compid", 1),
    }
    publish_command(client, t_sys, t_comp, payload)


def cmd_get_mission(args, cfg):
    client = mqtt_client(cfg)
    t_sys, t_comp = map(int, args.target.split(":"))
    payload = {
        "command": "MISSION_REQUEST_LIST",
        "params": [],
        "src_sysid": cfg.get("gcs_sysid", 250),
        "src_compid": cfg.get("gcs_compid", 1),
    }
    publish_command(client, t_sys, t_comp, payload)


def compute_hash(data: bytes) -> str:
    h = hashlib.sha256()
    h.update(data)
    return h.hexdigest()


def cmd_load_waypoints(args, cfg):
    path = Path(args.file)
    if not path.exists():
        print(f"Waypoint file not found: {path}")
        return
    raw = path.read_bytes()
    try:
        parsed = yaml.safe_load(raw)
    except Exception as e:
        print(f"Failed to parse yaml: {e}")
        return
    waypoints = parsed.get("waypoints") if isinstance(parsed, dict) else parsed
    if waypoints is None:
        print("No `waypoints` key found in YAML")
        return
    file_hash = compute_hash(raw)
    client = mqtt_client(cfg)
    t_sys, t_comp = map(int, args.target.split(":"))
    payload = {
        "action": "load_waypoints",
        "filename": str(path.name),
        "hash": file_hash,
        "waypoints": waypoints,
        "src_sysid": cfg.get("gcs_sysid", 250),
        "src_compid": cfg.get("gcs_compid", 1),
    }
    topic = f"command/{t_sys}/{t_comp}/load_waypoints"
    client.loop_start()
    client.publish(topic, json.dumps(payload))
    time.sleep(0.1)
    client.loop_stop()
    print(f"Published load_waypoints to {topic} (sha256={file_hash})")


def cmd_listen(args, cfg):
    client = mqtt_client(cfg)

    def on_connect(c, userdata, flags, rc):
        print("Connected to MQTT broker, subscribing to:", args.topic)
        c.subscribe(args.topic)

    def on_message(c, userdata, msg):
        try:
            payload = msg.payload.decode("utf-8")
            try:
                payload = json.loads(payload)
            except Exception:
                pass
            print(f"{msg.topic} -> {payload}")
        except Exception as e:
            print("Failed to decode message:", e)

    client.on_connect = on_connect
    client.on_message = on_message
    client.loop_start()
    client.connect(cfg["mqtt"]["host"], cfg["mqtt"]["port"], cfg["mqtt"].get("keepalive", 60))
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("Stopping listener")
    finally:
        client.loop_stop()


def cmd_mission_test(args, cfg):
    path = Path(args.file)
    if not path.exists():
        print(f"Waypoint file not found: {path}")
        return
    raw = path.read_bytes()
    try:
        parsed = yaml.safe_load(raw)
    except Exception as e:
        print(f"Failed to parse yaml: {e}")
        return
    waypoints = parsed.get("waypoints") if isinstance(parsed, dict) else parsed
    if waypoints is None:
        print("No `waypoints` key found in YAML")
        return
    print(f"Running mission test against {args.conn} with {len(waypoints)} waypoints...")
    res = mission_test.run_mission_test(args.conn, waypoints)
    print("Result:")
    print(json.dumps(res, indent=2))


def make_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Nomad backend CLI")
    sub = p.add_subparsers(dest="cmd")

    pa = sub.add_parser("arm", help="Arm or disarm a vehicle")
    pa.add_argument("--target", required=True, help="target as sys:comp, e.g. 3:1")
    pa.add_argument("--arm", action="store_true", help="Arm if present, otherwise disarm")
    pa.set_defaults(func=cmd_arm)

    pm = sub.add_parser("set-mode", help="Set flight mode (logical)")
    pm.add_argument("--target", required=True, help="target as sys:comp")
    pm.add_argument("--mode", required=True, help="mode name, e.g. GUIDED")
    pm.set_defaults(func=cmd_set_mode)

    pg = sub.add_parser("get-mission", help="Request mission list from vehicle")
    pg.add_argument("--target", required=True, help="target as sys:comp")
    pg.set_defaults(func=cmd_get_mission)

    pl = sub.add_parser("load-waypoints", help="Load waypoint YAML and publish load_waypoints")
    pl.add_argument("--target", required=True, help="target as sys:comp")
    pl.add_argument("--file", required=True, help="path to waypoint yaml")
    pl.set_defaults(func=cmd_load_waypoints)

    pt = sub.add_parser("mission-test", help="Run mission upload/download verification against a connection")
    pt.add_argument("--conn", required=True, help="pymavlink connection string, e.g. 'udpout:127.0.0.1:14550' or '/dev/ttyUSB0:57600'")
    pt.add_argument("--file", required=True, help="path to waypoint yaml to upload and verify")
    pt.set_defaults(func=cmd_mission_test)

    ps = sub.add_parser("listen", help="Listen and print MQTT messages for a topic filter")
    ps.add_argument("--topic", required=True, help="MQTT topic to subscribe to (supports +/#)")
    ps.set_defaults(func=cmd_listen)

    return p


def main(argv: List[str] | None = None):
    parser = make_parser()
    args = parser.parse_args(argv)
    cfg = load_config()
    if not hasattr(args, "func"):
        parser.print_help()
        return
    args.func(args, cfg)


if __name__ == "__main__":
    main()
