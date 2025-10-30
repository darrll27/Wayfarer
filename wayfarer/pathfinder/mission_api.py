import yaml
import json
import paho.mqtt.client as mqtt
import time
import os
import threading
from topic_schema import choose_command_topic, format_topic
from broker_config import load_common_mqtt_cfg
# import helpers we factored out
from helpers import (
    load_yaml, create_mqtt_client, fetch_manifest,
    load_manifest_cache, write_manifest_cache, manifest_cache_path, resolve_preflight_file,
    publish_mav_command
)
from threading import Event
from mission_tracker import MissionTracker

class Pathfinder:
    """
    Encapsulates pathfinder behavior: config loading, manifest fetch/cache,
    waypoint resolution, mission upload and command sending.
    """
    def __init__(self, config_path=None):
        self.base_dir = os.path.dirname(__file__)
        self.config_path = config_path or os.path.join(self.base_dir, "pathfinder.config.yaml")
        self.cfg = self._load_config()
        # Build MQTT config from common broker standard + overrides from config
        self.mqtt_cfg = load_common_mqtt_cfg(self.base_dir, self.cfg.get("mqtt"))
        self.topic_prefix = self.mqtt_cfg.get("topic_prefix", "wayfarer/v1")
        # Monitoring settings (optional in config under 'monitoring')
        mon = self.cfg.get("monitoring") if isinstance(self.cfg.get("monitoring"), dict) else {}
        self.monitor_publish_hz = float((mon or {}).get("publish_hz", 1.0))
        # Default to 60s post-start if unspecified
        self.monitor_duration_secs = (mon or {}).get("duration_secs", 60)

    def _load_config(self):
        if os.path.exists(self.config_path):
            with open(self.config_path, "r") as fh:
                return yaml.safe_load(fh)
        return {}

    # MQTT client factory uses helper
    def create_mqtt_client(self, client_id):
        return create_mqtt_client(client_id)

    # manifest cache helpers now use helper functions
    def _manifest_cache_path(self):
        return manifest_cache_path(self.base_dir)

    def _load_manifest_cache(self):
        return load_manifest_cache(self.base_dir)

    def _write_manifest_cache(self, manifest):
        return write_manifest_cache(self.base_dir, manifest)

    # manifest fetch delegates to helper
    def fetch_manifest(self, client, timeout=2.0):
        return fetch_manifest(client, self.topic_prefix, timeout=timeout)

    # topic formatting uses helper
    def format_topic(self, manifest, key, **kwargs):
        return format_topic(manifest, key, **kwargs)

    # waypoint resolution (simple rule) -- unchanged
    def resolve_waypoint_file(self, group_name, group):
        default_wp_folder = self.cfg.get('waypoints_folder', 'waypoints')
        effective_waypoint_type = self.cfg.get('waypoint_type')
        if 'waypoint_type' in group:
            effective_waypoint_type = group['waypoint_type']
        folder = group.get('waypoints_folder', default_wp_folder)
        base = group_name.split('_', 1)[0]
        parts = [self.base_dir, folder]
        if effective_waypoint_type:
            parts.append(effective_waypoint_type)
        parts.append(f"{base}.yaml")
        return os.path.join(*parts)

    # publish helper
    def publish_json(self, client, topic, payload, qos=0, retain=False):
        client.publish(topic, json.dumps(payload), qos=qos, retain=retain)

    # high-level run for a group (used by multiprocessing entrypoint)
    def run_group(self, group_name):
        group = self.cfg.get("groups", {}).get(group_name)
        if not group:
            print(f"[{group_name}] no group config found in {self.config_path}")
            return

        # create tracker for logs
        tracker = MissionTracker(self.base_dir, publish_on_save=True)

        client_id = self.mqtt_cfg.get('client_id','pathfinder') + f"-{group_name}"
        client = self.create_mqtt_client(client_id)
        client.connect(self.mqtt_cfg.get('host','localhost'), self.mqtt_cfg.get('port',1883))
        client.loop_start()

        # fetch manifest (live or cached)
        manifest = self.fetch_manifest(client, timeout=2.0)
        if manifest:
            cached = self._load_manifest_cache()
            try:
                same = (json.dumps(cached, sort_keys=True) == json.dumps(manifest, sort_keys=True)) if cached is not None else False
            except Exception:
                same = False
            if not same:
                if self._write_manifest_cache(manifest):
                    print(f"[{group_name}] manifest fetched and cache updated at {self._manifest_cache_path()}")
                else:
                    print(f"[{group_name}] manifest fetched but failed to update cache")
            else:
                print(f"[{group_name}] manifest fetched (no change)")
        else:
            cached = self._load_manifest_cache()
            if cached:
                manifest = cached
                print(f"[{group_name}] no live manifest; using cached manifest at {self._manifest_cache_path()}")
            else:
                print(f"[{group_name}] ERROR: manifest not found and no cache present — aborting")
                client.loop_stop()
                client.disconnect()
                return

        topics = manifest.get("topics", {}) if isinstance(manifest, dict) else {}
        if "mission_upload" not in topics or "cmd" not in topics:
            print(f"[{group_name}] ERROR: manifest missing required topic patterns (mission_upload/cmd) — aborting")
            client.loop_stop()
            client.disconnect()
            return

        wp_path = self.resolve_waypoint_file(group_name, group)
        if not wp_path or not os.path.exists(wp_path):
            print(f"[{group_name}] Waypoint file not found: {wp_path}")
            client.loop_stop()
            client.disconnect()
            return
        raw_waypoints = load_yaml(wp_path).get('waypoints', [])
        waypoint_type = group.get('waypoint_type', self.cfg.get('waypoint_type','absolute'))

        # Map action strings to MAV_CMD values
        ACTION_TO_CMD = {
            "takeoff": 22,   # MAV_CMD_NAV_TAKEOFF
            "waypoint": 16,  # MAV_CMD_NAV_WAYPOINT
            "land": 21,      # MAV_CMD_NAV_LAND
        }
        # Use LOCAL_NED frame for relative missions
        FRAME_LOCAL_NED = 3

        def to_mission_item(idx, item):
            item = dict(item)
            item.pop("comments", None)
            action = item.get("action")
            if action not in ACTION_TO_CMD:
                raise ValueError(f"Invalid action '{action}' in waypoint. Allowed actions: {list(ACTION_TO_CMD.keys())}")
            command = ACTION_TO_CMD[action]
            sysid = item.get("sysid")
            if sysid is None:
                sysids = group.get('sysids')
                sysid = sysids[0] if isinstance(sysids, list) and sysids else sysids if sysids else None
            mission_item = {
                "command": command,
                "current": 0,
                "autocontinue": 1,
                "params": [0,0,0,0],
                "sysid": sysid,
                "seq": idx
            }
            # If lat/lon/alt present, treat as global and set frame=6
            if all(k in item for k in ("lat", "lon", "alt")):
                mission_item["lat"] = item["lat"]
                mission_item["lon"] = item["lon"]
                mission_item["alt"] = item["alt"]
                mission_item["frame"] = item.get("frame", 6)
            # If x/y/z present, treat as local and set frame=3
            elif all(k in item for k in ("x", "y", "z")):
                mission_item["x"] = item["x"]
                mission_item["y"] = item["y"]
                mission_item["z"] = item["z"]
                mission_item["frame"] = item.get("frame", 3)
            # Only include frame if explicitly set otherwise
            elif "frame" in item:
                mission_item["frame"] = item["frame"]
            return mission_item

        # Ensure sysid, compid, and device_id are set from group config
        sysids = group.get('sysids')
        if isinstance(sysids, list) and sysids:
            sysid = sysids[0]
        else:
            sysid = sysids if sysids is not None else 1
        compid = 1  # Set your target component id as needed
        device_id = f"mav_sys{sysid}"

        waypoints = [to_mission_item(idx, item) for idx, item in enumerate(raw_waypoints)]

        # --- Mission upload to all sysids ---
        self._send_mission_upload_to_all(client, manifest, group_name, group, waypoints, compid)

        # Do not block on mission ACK; Wayfarer handles MAVLink handshake internally

        # resolve optional preflight file (group-specific or shared). If none found, fall back to
        # a `preflight` sequence defined directly in the main config (common to all drones).
        preflight_path = resolve_preflight_file(self.base_dir, group_name, group, default_wp_folder=self.cfg.get('waypoints_folder','waypoints'))
        if preflight_path and os.path.exists(preflight_path):
            preflight = load_yaml(preflight_path).get("preflight", []) if isinstance(load_yaml(preflight_path), dict) else load_yaml(preflight_path)
            print(f"[{group_name}] executing preflight from {preflight_path} ({len(preflight)} items)")
            # don't execute here; we'll run per-sysid below
        else:
            # fallback to `preflight` key in the main config (common preflight for all groups)
            cfg_pf = self.cfg.get('preflight')
            if isinstance(cfg_pf, list) and cfg_pf:
                preflight = cfg_pf
                print(f"[{group_name}] using preflight from main config (path: {self.config_path}) ({len(preflight)} items)")
            else:
                preflight = []

        # detect if preflight already includes an arming command (MAV_CMD_COMPONENT_ARM_DISARM == 400)
        preflight_has_arm = any((isinstance(item, dict) and (item.get("command") == 400 or item.get("action") == "arm")) for item in preflight)

        sysids_list = group.get('sysids', []) or []
        stagger_secs = float(group.get('stagger_secs', self.cfg.get('stagger_secs', 0)))

        def sysid_worker(sysid, start_delay):
            try:
                if start_delay > 0:
                    time.sleep(start_delay)

                device_id = f"mav_sys{sysid}"

                # discovery (optional)
                discovery_topic = self.format_topic(manifest, "discovery", device_id=device_id, sysid=sysid)
                if discovery_topic:
                    discovery_payload = {"schema": "mavlink", "sysid": sysid, "source": "pathfinder"}
                    self.publish_json(client, discovery_topic, discovery_payload, qos=self.mqtt_cfg.get("qos",0), retain=True)
                    tracker.record_command(sysid, action="discovery", topic=discovery_topic, payload=discovery_payload)
                    tracker.publish_log(client, self.topic_prefix, sysid, qos=self.mqtt_cfg.get("qos",0))
                    print(f"[{group_name}-{sysid}] Published discovery -> {discovery_topic}")

                time.sleep(1)

                # execute preflight commands (per-sysid) before takeoff
                if preflight:
                    for item in preflight:
                        cmd = item.get("command")
                        params = item.get("params", [0]*7)
                        cmd_topic, chosen_key = publish_mav_command(
                            client, manifest, sysid, device_id, cmd, params=params,
                            action=item.get("action", "preflight"), qos=self.mqtt_cfg.get("qos", 0),
                            tracker=tracker, topic_prefix=self.topic_prefix
                        )
                        if not cmd_topic:
                            print(f"[{group_name}-{sysid}] ERROR: no command topic resolved for preflight command — aborting")
                            return
                        print(f"[{group_name}-{sysid}] Sent preflight cmd -> [{chosen_key}] {cmd_topic}")
                        time.sleep(item.get("delay", 0.5))

                # send ARM if preflight didn't include it already
                if not preflight_has_arm:
                    arm_cmd = 400  # MAV_CMD_COMPONENT_ARM_DISARM
                    arm_params = [1, 0, 0, 0, 0, 0, 0]
                    cmd_topic, chosen_key = publish_mav_command(
                        client, manifest, sysid, device_id, arm_cmd, params=arm_params,
                        action="arm", qos=self.mqtt_cfg.get("qos",0), tracker=tracker, topic_prefix=self.topic_prefix
                    )
                    if not cmd_topic:
                        print(f"[{group_name}-{sysid}] ERROR: no command topic resolved for arm — aborting")
                        return
                    print(f"[{group_name}-{sysid}] Sent arm via [{chosen_key}] -> {cmd_topic}")
                    time.sleep(1)

                # choose best command topic using centralized resolver
                cmd_topic, chosen_key = choose_command_topic(manifest, sysid, device_id=device_id, action="takeoff")
                if not cmd_topic:
                    print(f"[{group_name}-{sysid}] ERROR: no command topic resolved for takeoff — aborting")
                    return
                # choose altitude and MAV command depending on waypoint type
                if waypoint_type == "absolute":
                    takeoff_alt = waypoints[0].get("alt", 10)
                    takeoff_cmd = 22
                else:
                    takeoff_alt = waypoints[0].get("z", 10)
                    takeoff_cmd = 24

                takeoff_params = [0, 0, 0, 0, 0, 0, takeoff_alt]

                cmd_topic, chosen_key = publish_mav_command(
                    client, manifest, sysid, device_id, takeoff_cmd, params=takeoff_params,
                    action="takeoff", qos=self.mqtt_cfg.get("qos",0), tracker=tracker, topic_prefix=self.topic_prefix
                )
                if not cmd_topic:
                    print(f"[{group_name}] ERROR: no command topic resolved for takeoff — aborting")
                    return
                print(f"[{group_name}-{sysid}] Sent takeoff via [{chosen_key}] -> {cmd_topic}")

                time.sleep(2)

                # start mission (existing logic) - record & publish
                cmd_topic, chosen_key = choose_command_topic(manifest, sysid, device_id=device_id, action="start")
                if not cmd_topic:
                    print(f"[{group_name}-{sysid}] ERROR: no command topic resolved for start — aborting")
                    return
                start_params = [0,0,0,0,0,0,0]
                cmd_topic, chosen_key = publish_mav_command(
                    client, manifest, sysid, device_id, 300, params=start_params,
                    action="start", qos=self.mqtt_cfg.get("qos",0), tracker=tracker, topic_prefix=self.topic_prefix
                )
                if not cmd_topic:
                    print(f"[{group_name}] ERROR: no command topic resolved for start — aborting")
                    return
                print(f"[{group_name}-{sysid}] Sent start via [{chosen_key}] -> {cmd_topic}")
            except Exception:
                # keep worker resilient
                pass

        threads = []
        for idx, sid in enumerate(sysids_list):
            delay = idx * max(stagger_secs, 0.0)
            t = threading.Thread(target=sysid_worker, args=(sid, delay), daemon=True)
            t.start()
            threads.append(t)

        # --- Start continued active monitoring (GPS + checkpoint) ---
        self._start_active_monitoring(client, manifest, group_name, group)

        # Keep client alive for monitoring duration then close
        try:
            time.sleep(float(self.monitor_duration_secs))
        except Exception:
            pass
        client.loop_stop()
        client.disconnect()

    # --- helpers ---
    def _send_mission_upload_to_all(self, client, manifest, group_name, group, waypoints, compid=1):
        sysids = group.get('sysids') or []
        if not isinstance(sysids, list):
            sysids = [sysids]
        if not sysids:
            sysids = [1]
        for sid in sysids:
            device_id = f"mav_sys{sid}"
            mission_upload_topic = self.format_topic(manifest, "mission_upload", sysid=sid, device_id=device_id)
            mission_upload_payload = {
                "msg_type": "MISSION_UPLOAD",
                "sysid": sid,
                "compid": compid,
                "mission_items": waypoints
            }
            self.publish_json(client, mission_upload_topic, mission_upload_payload, qos=self.mqtt_cfg.get("qos",0))
            print(f"[{group_name}-{sid}] Sent MISSION_UPLOAD with {len(waypoints)} items -> {mission_upload_topic}")

    def _start_active_monitoring(self, client, manifest, group_name, group):
        """Subscribe to raw MAVLink telemetry and publish per-sysid state (GPS + checkpoint).
        Publishes to: {topic_prefix}/pathfinder/sysid_<sysid>/state
        """
        root = self.topic_prefix
        topic_filter = f"{root}/devices/+/telem/raw/mavlink/+"
        client.subscribe(topic_filter, qos=0)

        # Build device_id -> sysid map
        devmap = {}
        try:
            for dev_id, info in (manifest.get("devices") or {}).items():
                sid = info.get("sysid")
                if sid is not None:
                    devmap[dev_id] = int(sid)
        except Exception:
            pass

        group_sysids = set(group.get('sysids', []) or [])
        last_seq = {}
        last_gps = {}

        def on_raw(_cl, _ud, msg):
            try:
                payload = json.loads(msg.payload.decode("utf-8"))
            except Exception:
                try:
                    payload = yaml.safe_load(msg.payload)
                except Exception:
                    return
            parts = msg.topic.split('/')
            mtype = parts[-1] if parts else None
            # extract device_id from topic
            device_id = None
            try:
                didx = parts.index('devices') + 1
                device_id = parts[didx]
            except Exception:
                device_id = None
            sysid = devmap.get(device_id)
            if group_sysids and (sysid not in group_sysids):
                return

            if mtype == 'MISSION_CURRENT':
                seq = payload.get('seq')
                if seq is not None and sysid is not None:
                    last_seq[sysid] = int(seq)
            elif mtype in ('GLOBAL_POSITION_INT', 'GPS_RAW_INT', 'GPS2_RAW'):
                lat = payload.get('lat')
                lon = payload.get('lon')
                alt = payload.get('alt') or payload.get('alt_ellipsoid') or payload.get('alt_msl')
                try:
                    if isinstance(lat, (int, float)) and abs(lat) > 90:
                        lat = lat / 1e7
                    if isinstance(lon, (int, float)) and abs(lon) > 180:
                        lon = lon / 1e7
                    if isinstance(alt, (int, float)) and abs(alt) > 10000:
                        alt = alt / 1000.0
                except Exception:
                    pass
                if (lat is not None) and (lon is not None) and (sysid is not None):
                    last_gps[sysid] = {"lat": float(lat), "lon": float(lon), "alt": float(alt) if alt is not None else None}

        client.message_callback_add(topic_filter, on_raw)

        def publisher_loop():
            period = 1.0 / max(self.monitor_publish_hz, 0.1)
            while True:
                now = time.time()
                targets = group_sysids or set(last_gps.keys())
                for sid in targets:
                    state = {"group": group_name, "sysid": sid, "checkpoint": last_seq.get(sid), "t": now}
                    gps = last_gps.get(sid)
                    if gps:
                        state.update({"lat": gps.get("lat"), "lon": gps.get("lon"), "alt": gps.get("alt")})
                    topic = f"{root}/pathfinder/sysid_{sid}/state"
                    try:
                        client.publish(topic, json.dumps(state), qos=self.mqtt_cfg.get("qos",0), retain=False)
                    except Exception:
                        pass
                time.sleep(period)

        threading.Thread(target=publisher_loop, daemon=True).start()

# module-level helper for multiprocessing entrypoint (picklable)
def run_group_process(config_path, group_name):
    p = Pathfinder(config_path)
    p.run_group(group_name)
    return


