"""Helper utilities for the Pathfinder CLI and missions.

Responsibilities:
    - Small I/O helpers (load/write YAML/JSON)
    - MQTT client factory
    - Manifest cache helpers
    - High-level publish helpers (e.g. publish_mav_command)

Topic formatting and resolution is intentionally delegated to `topic_schema.py`.
"""

import os
import json
import yaml
import paho.mqtt.client as mqtt
from threading import Event
from topic_schema import format_topic, choose_command_topic

def load_yaml(path):
    with open(path, 'r') as f:
        return yaml.safe_load(f)

def create_mqtt_client(client_id):
    try:
        return mqtt.Client(client_id=client_id, callback_api_version=1)
    except TypeError:
        return mqtt.Client(client_id=client_id)
    except Exception:
        return mqtt.Client(client_id=client_id)

def manifest_cache_path(base_dir):
    cache_dir = os.path.join(base_dir, ".cache")
    os.makedirs(cache_dir, exist_ok=True)
    return os.path.join(cache_dir, "wayfarer_manifest.json")

def load_manifest_cache(base_dir):
    path = manifest_cache_path(base_dir)
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r") as fh:
            return json.load(fh)
    except Exception:
        return None

def write_manifest_cache(base_dir, manifest):
    path = manifest_cache_path(base_dir)
    try:
        with open(path, "w") as fh:
            json.dump(manifest, fh, indent=2, sort_keys=True)
        return True
    except Exception:
        return False

def fetch_manifest(client, topic_prefix, timeout=2.0):
    """
    Subscribe once to the retained bridge manifest and return the dict.
    Returns None on timeout or parse error.
    """
    manifest_topic = f"{topic_prefix}/bridge/manifest"
    ev = Event()
    result = {"payload": None}

    def on_message(cl, userdata, msg):
        try:
            result["payload"] = json.loads(msg.payload.decode("utf-8"))
        except Exception:
            try:
                result["payload"] = yaml.safe_load(msg.payload)
            except Exception:
                result["payload"] = None
        finally:
            ev.set()

    client.subscribe(manifest_topic, qos=0)
    client.message_callback_add(manifest_topic, on_message)
    ev.wait(timeout=timeout)
    client.message_callback_remove(manifest_topic)
    return result["payload"]

# topic formatting/resolution is provided by topic_schema.format_topic and choose_command_topic


def publish_mav_command(client, manifest, sysid, device_id, command, params=None, action="preflight", qos=0, tracker=None, topic_prefix=None, retain=False):
    """
    Resolve a command topic from the manifest (using the command priority), build a
    normalized COMMAND_LONG payload and publish it. If tracker is provided, record
    the command and optionally publish the per-device log using topic_prefix.

    Returns (topic, chosen_key) on success, or (None, None) if no topic could be resolved.
    """
    params = params or [0] * 7
    payload = {"schema": "mavlink", "msg_type": "COMMAND_LONG", "sysid": sysid, "command": command, "params": params}

    # resolve best command topic (delegate to topic_schema)
    cmd_topic, chosen_key = choose_command_topic(manifest, sysid, device_id=device_id, action=action)
    if not cmd_topic:
        # fallback to cmd pattern if present
        cmd_topic = format_topic(manifest, "cmd", sysid=sysid, device_id=device_id, action=action)
        chosen_key = "cmd" if cmd_topic else None
    if not cmd_topic:
        return None, None

    # include device_id when publishing to cmd topic so bridge can route
    if chosen_key == "cmd":
        payload["device_id"] = device_id

    # publish
    client.publish(cmd_topic, json.dumps(payload), qos=qos, retain=bool(retain))

    # track
    if tracker is not None:
        try:
            tracker.record_command(sysid, action=action, topic=cmd_topic, payload=payload)
            if topic_prefix:
                tracker.publish_log(client, topic_prefix, sysid, qos=qos)
        except Exception:
            pass

    return cmd_topic, chosen_key

def resolve_preflight_file(base_dir, group_name, group, default_wp_folder="waypoints"):
    """
    Resolution rule for preflight file:
      1) group['preflight_file'] if present (relative to base_dir)
      2) base_dir / default_wp_folder / "preflight" / <base>.yaml
      3) base_dir / "pre-flight.yaml"
    Return path or None.
    """
    # 1) explicit
    if 'preflight_file' in group:
        wf = group['preflight_file']
        if os.path.isabs(wf):
            return wf
        cand = os.path.join(base_dir, wf)
        if os.path.exists(cand):
            return cand
        cand2 = os.path.join(base_dir, default_wp_folder, wf)
        if os.path.exists(cand2):
            return cand2
        # if specified but not found, return candidate (caller will check existence)
        return cand

    # 2) per-base preflight: waypoints/preflight/<base>.yaml
    base = group_name.split('_', 1)[0]
    cand = os.path.join(base_dir, default_wp_folder, "preflight", f"{base}.yaml")
    if os.path.exists(cand):
        return cand

    # 3) top-level pre-flight.yaml
    top = os.path.join(base_dir, "pre-flight.yaml")
    if os.path.exists(top):
        return top

    return None

def write_yaml_log(base_dir, device_id, data):
    """
    Write YAML log for device under .logs/<device_id>.yaml (append entries).
    'data' is a list of events or dict; overwrite with latest list.
    """
    log_dir = os.path.join(base_dir, ".logs")
    os.makedirs(log_dir, exist_ok=True)
    path = os.path.join(log_dir, f"{device_id}.yaml")
    try:
        with open(path, "w") as fh:
            yaml.safe_dump(data, fh, sort_keys=False)
        return path
    except Exception:
        return None
