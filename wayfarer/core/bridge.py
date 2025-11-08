import json, time, threading
from pymavlink import mavutil
from queue import Queue
from wayfarer.core.registry import DeviceRegistry
from wayfarer.core.constants import (
    TOPIC_VERSION, DISCOVERY_TOPIC, HEARTBEAT_TOPIC, RAW_MAVLINK_TOPIC,
    MISSION_UPLOAD_TOPIC, CMD_ROOT_TOPIC
)
from wayfarer.core.packet import Packet
from wayfarer.core.router import RouteTable
from wayfarer.core.utils import safe_json
from wayfarer.core import command_mapper

class Bridge:
    def __init__(self, cfg: dict, transports: dict, mqtt_router):
        self.cfg = cfg
        self.registry = DeviceRegistry()
        self.routes = RouteTable(cfg.get("routes", []))
        self.transports = transports
        self.mqtt = mqtt_router
        self.root = cfg["mqtt"].get("topic_prefix", TOPIC_VERSION)
        # Inbound telemetry/events queue (from transports -> MQTT)
        self.q = Queue(maxsize=10000)
        # Outbound command queue (from producers like GCS -> transports)
        self.q_out = Queue(maxsize=10000)
        self._run = False
        # threads created by start(); stored so we can join on stop()
        self._threads = []
        # High-level GCS behavior (optional configuration)
        gcs_raw = cfg.get("gcs")
        gcs_cfg = gcs_raw if isinstance(gcs_raw, dict) else {}
        # Keep default enabled unless explicitly disabled in config
        self.gcs_enabled = bool(gcs_cfg.get("enabled", True))
        self.gcs_heartbeat_interval = float(gcs_cfg.get("heartbeat_interval", 1.0))
        self.gcs_request_rate = int(gcs_cfg.get("request_rate", 10))
        self.gcs_sysid = gcs_cfg.get("sysid")
        self.gcs_compid = gcs_cfg.get("compid")
        # Derive MQTT device_id for GCS publications immediately.
        # No fallbacks: if sysid not provided, we disable the GCS loop.
        try:
            if self.gcs_sysid is not None:
                self.gcs_device_id = f"mav_sys{int(self.gcs_sysid)}"
            else:
                self.gcs_device_id = None
                self.gcs_enabled = False
        except Exception:
            self.gcs_device_id = None
            self.gcs_enabled = False

    # --- lifecycle ---
    def start(self):
        self._run = True
        # start MQTT and subscribe to device-agnostic command and mission upload topics only
        self.mqtt.start()
        # Subscribe to generic command topic (all actions)
        self.mqtt.subscribe_cmd(CMD_ROOT_TOPIC.format(root=self.root, action="+"))
        # Subscribe to generic mission upload topic
        self.mqtt.subscribe_cmd(MISSION_UPLOAD_TOPIC.format(root=self.root))

        # publish manifest so external APIs can discover exact topics/patterns
        # publish immediately (before transports start) so manifest is available
        # even when no devices have been discovered yet.
        try:
            self.publish_manifest()
        except Exception:
            pass

        # publish the canonical wayfarer topic template (retained) so clients can discover
        try:
            # lazy publish; won't raise if publisher module is missing
            self._publish_template()
        except Exception:
            pass

        # start transports
        for t in self.transports.values():
            t.start()
        # workers (store thread references so we can join on stop)
        t = threading.Thread(target=self._proc_loop, daemon=False)
        t.start()
        self._threads.append(t)
        t = threading.Thread(target=self._heartbeat_loop, daemon=False)
        t.start()
        self._threads.append(t)
        t = threading.Thread(target=self._route_loop, daemon=False)
        t.start()
        self._threads.append(t)
        if self.gcs_enabled:
            t = threading.Thread(target=self._gcs_loop, daemon=False)
            t.start()
            self._threads.append(t)

    def stop(self):
        self._run = False
        for t in self.transports.values():
            t.stop()
        self.mqtt.stop()
        # Unblock queue.get() calls by pushing sentinel values where appropriate.
        try:
            # best effort - ignore if full
            self.q.put_nowait(None)
        except Exception:
            pass
        try:
            self.q_out.put_nowait(None)
        except Exception:
            pass

        # Join worker threads with a short timeout each
        for thr in getattr(self, "_threads", []):
            try:
                thr.join(timeout=2.0)
            except Exception:
                pass

    # --- called by transports ---
    def on_discover_mav(self, sysid: int, origin_name: str) -> str:
        device_id = self.registry.upsert_mav(sysid, origin_name)
        topic = DISCOVERY_TOPIC.format(root=self.root, device_id=device_id)
        self.mqtt.publish_telem(topic, {
            "schema":"mavlink","sysid":sysid,"status":"discovered",
            "transports": list(self.registry.transports_for(device_id))
        }, retain=True)

        # update manifest when new device discovered
        try:
            self.publish_manifest()
            # re-publish canonical topic template so manifest + template remain in sync
            try:
                self._publish_template()
            except Exception:
                pass
        except Exception:
            pass
        return device_id

    def on_transport_packet(self, pkt: Packet):
        # enqueue for processing -> MQTT publish
        try:
            self.q.put_nowait(pkt)
        except Exception:
            pass

    # --- MQTT -> transports (commands) ---
    def on_cmd(self, topic: str, data: bytes):
        # Support both topic forms, but always enqueue to route loop (no direct writes):
        #  - per-device: {root}/devices/<device_id>/cmd/<action>
        #  - global:     {root}/cmd/<action> (payload may include device_id/sysid)
        try:
            payload = json.loads(data.decode("utf-8"))
        except Exception:
            return

        parts = topic.split("/")
        device_id = None
        if "devices" in parts:
            try:
                idx = parts.index("devices")
                device_id = parts[idx + 1]
            except Exception:
                device_id = None
        else:
            device_id = payload.get("device_id")
            if not device_id and "sysid" in payload:
                try:
                    device_id = self.registry.device_id_for_mav(int(payload.get("sysid")))
                except Exception:
                    device_id = None

        is_mission_upload = topic.endswith('/mission/upload') or '/mission/upload' in topic
        pkt = Packet(
            device_id=device_id,
            schema=payload.get("schema", "mavlink"),
            msg_type=("MISSION_UPLOAD" if is_mission_upload else payload.get("msg_type", "raw")),
            fields=payload,
            timestamp=time.time(),
            origin="mqtt"
        )
        try:
            self.q_out.put_nowait(pkt)
        except Exception:
            pass

    # --- internal workers ---
    def _proc_loop(self):
        while self._run:
            pkt = self.q.get()
            # None is a shutdown sentinel pushed by stop()
            if pkt is None:
                break
            if pkt.schema == "mavlink":
                # publish raw
                topic = RAW_MAVLINK_TOPIC.format(
                    root=self.root, device_id=pkt.device_id, msg=pkt.msg_type
                )
                self.mqtt.publish_telem(topic, safe_json(pkt.fields))

                # minimal normalized example for ATTITUDE
                if pkt.msg_type == "ATTITUDE":
                    self.mqtt.publish_telem(
                        f"{self.root}/devices/{pkt.device_id}/telem/pose/attitude",
                        {
                            "roll": pkt.fields.get("roll"),
                            "pitch": pkt.fields.get("pitch"),
                            "yaw": pkt.fields.get("yaw"),
                            "rollspeed": pkt.fields.get("rollspeed"),
                            "pitchspeed": pkt.fields.get("pitchspeed"),
                            "yawspeed": pkt.fields.get("yawspeed"),
                            "t": pkt.timestamp,
                        }
                    )
                    #print(f"[DEBUG] on_cmd: sending to transport={{pkt.device_id}} ATTITUDE published")

    def _heartbeat_loop(self):
        interval = float(self.cfg.get("mqtt",{}).get("heartbeat_secs", 2.0))
        while self._run:
            snap = self.registry.snapshot()
            for device_id in snap.keys():
                topic = HEARTBEAT_TOPIC.format(root=self.root, device_id=device_id)
                self.mqtt.publish_telem(topic, {"status":"online","ts":time.time()}, retain=True)
            # Always publish bridge manifest as a heartbeat (retained) so manifest stays observable
            try:
                self.publish_manifest()
            except Exception:
                pass
            time.sleep(interval)

    def _route_loop(self):
        """Route outbound Packets from producers (e.g., GCS) to transports based on routes table.
        No implicit broadcast: if no route matches the packet.origin, we log and drop.
        """
        while self._run:
            pkt = self.q_out.get()
            # None is our shutdown sentinel
            if pkt is None:
                break
            try:
                outs = self.routes.outputs_for(pkt.origin)
                if not outs:
                    print(f"[WARN] No route outputs for origin={pkt.origin}; dropping msg_type={pkt.msg_type}")
                    continue
                for pat in outs:
                    # pattern may be specific transport name or wildcard
                    for name, t in self.transports.items():
                        try:
                            import fnmatch
                            if fnmatch.fnmatch(name, pat):
                                t.write(pkt)
                        except Exception:
                            pass
            except Exception:
                pass

    def _gcs_loop(self):
        """Continuously emit GCS HEARTBEAT + REQUEST_DATA_STREAM via all transports.
        Uses optional cfg['gcs'] for interval, rate, and transport source identity.
        """
        while self._run and self.gcs_enabled:
            try:
                # Build GCS-style heartbeat matching common GCS values
                hb_fields = {
                    "mavpackettype": "HEARTBEAT",
                    "type": int(getattr(mavutil.mavlink, "MAV_TYPE_GCS", 6)),
                    "autopilot": int(getattr(mavutil.mavlink, "MAV_AUTOPILOT_INVALID", 8)),
                    "base_mode": 192,
                    "custom_mode": 0,
                    "system_status": 4,
                    "mavlink_version": 3,
                }
                # Enqueue outbound to route loop (no direct writes)
                try:
                    hb_pkt = Packet(device_id=self.gcs_device_id, schema="mavlink", msg_type="HEARTBEAT", fields=hb_fields, timestamp=time.time(), origin="mavlink_gcs")
                    self.q_out.put_nowait(hb_pkt)
                except Exception:
                    pass
                try:
                    rds_fields = {
                        "target_system": 0,
                        "target_component": 0,
                        "req_stream_id": int(getattr(mavutil.mavlink, "MAV_DATA_STREAM_ALL", 0)),
                        "req_message_rate": int(self.gcs_request_rate),
                        "start_stop": 1,
                    }
                    rds_pkt = Packet(device_id=self.gcs_device_id, schema="mavlink", msg_type="REQUEST_DATA_STREAM", fields=rds_fields, timestamp=time.time(), origin="mavlink_gcs")
                    self.q_out.put_nowait(rds_pkt)
                except Exception:
                    pass
                # Also enqueue both to inbound -> MQTT raw publish for observability
                try:
                    self.q.put_nowait(hb_pkt)
                except Exception:
                    pass
                try:
                    self.q.put_nowait(rds_pkt)
                except Exception:
                    pass
                # Publish GCS heartbeat topic explicitly (virtual emitter not in registry)
                try:
                    if self.gcs_device_id:
                        topic = HEARTBEAT_TOPIC.format(root=self.root, device_id=self.gcs_device_id)
                        self.mqtt.publish_telem(topic, {"status": "online", "ts": time.time()}, retain=True)
                except Exception:
                    pass
            except Exception:
                pass
            time.sleep(self.gcs_heartbeat_interval)

    def publish_manifest(self):
        """
        Publish an observable, retained manifest describing:
          - canonical topic patterns (including the /cmd patterns)
          - transports known to the bridge
          - configured routes
          - snapshot of discovered devices
          - mapper capabilities (what msg_types are supported)
          - usage examples for commands and mission upload so clients know how to use the API
        Other APIs can subscribe to {root}/bridge/manifest to discover exact topics to publish to.
        """
        manifest_topic = f"{self.root}/bridge/manifest"
        manifest = {
            "bridge_root": self.root,
            "topics": {
                "cmd": CMD_ROOT_TOPIC.format(root=self.root, action="{action}"),
                "mission_upload": MISSION_UPLOAD_TOPIC.format(root=self.root),
                "raw_mavlink": RAW_MAVLINK_TOPIC.format(root=self.root, device_id="{device_id}", msg="{msg}"),
                "discovery": DISCOVERY_TOPIC.format(root=self.root, device_id="{device_id}"),
                "heartbeat": HEARTBEAT_TOPIC.format(root=self.root, device_id="{device_id}")
            },
            "transports": list(self.transports.keys()),
            "routes": self.cfg.get("routes", []),
            "gcs": {
                "enabled": self.gcs_enabled,
                "heartbeat_interval": self.gcs_heartbeat_interval,
                "request_rate": self.gcs_request_rate,
                "sysid": self.gcs_sysid,
                "compid": self.gcs_compid,
                "device_id": self.gcs_device_id,
            },
            "devices": self.registry.snapshot(),
            "mapper": {
                "supported_msg_types": command_mapper.get_supported_msg_types(),
                "notes": "Commands published to command topics will be normalized and forwarded to transports by the bridge."
            },
            "usage_examples": {
                "simple_cmd": {
                    "topic": f"{self.root}/devices/{{device_id}}/cmd/takeoff",
                    "payload": { "schema": "mavlink", "msg_type": "COMMAND_LONG", "command": 22, "params": [0,0,0,0,0,0,20] }
                },
                "global_cmd": {
                    "topic": f"{self.root}/cmd/takeoff",
                    "notes": "Use when you prefer a single command topic; include device_id or sysid in payload.",
                    "payload": { "device_id": "mav_sys1", "schema": "mavlink", "msg_type": "COMMAND_LONG", "command": 22, "params": [0,0,0,0,0,0,20] }
                },
                "mission_upload": {
                    "topic": f"{self.root}/sysid_{{sysid}}/mission/upload",
                    "payload": { "sysid": 1, "mission_items": [ { "lat": 37.7749, "lon": -122.4194, "alt": 50 } ], "waypoint_type": "absolute" }
                },
                "command_long_direct": {
                    "topic": f"{self.root}/sysid_{{sysid}}/command/long",
                    "payload": { "sysid": 1, "command": 22, "params": [0,0,0,0,0,0,20] }
                }
            }
        }
        # publish retained so late clients can discover it
        self.mqtt.publish_telem(manifest_topic, manifest, retain=True)

    def _publish_template(self):
        """
        Lazy import and publish the canonical wayfarer topic template for wayfarer.
        Returns True if publish was attempted successfully, False otherwise.
        This avoids import-time failures when the publisher module isn't available
        (e.g., different install layouts).
        """
        try:
            import importlib
            mod = importlib.import_module("wayfarer.core.publisher")
            publish_for_wayfarer = getattr(mod, "publish_for_wayfarer", None)
            if publish_for_wayfarer is None:
                return False
        except Exception:
            return False
        try:
            publish_for_wayfarer(retain=True)
            return True
        except Exception:
            return False
