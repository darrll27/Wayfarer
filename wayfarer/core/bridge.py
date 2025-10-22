import json, time, threading
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
        self.q = Queue(maxsize=10000)
        self._run = False

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
        # workers
        threading.Thread(target=self._proc_loop, daemon=True).start()
        threading.Thread(target=self._heartbeat_loop, daemon=True).start()

    def stop(self):
        self._run = False
        for t in self.transports.values():
            t.stop()
        self.mqtt.stop()

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
        # Support both:
        #  - per-device: {root}/devices/<device_id>/cmd/<action>
        #  - global:     {root}/cmd/<action>  (payload must include "device_id" or "sysid")
        try:
            payload = json.loads(data.decode("utf-8"))
        except Exception:
            return

        parts = topic.split("/")
        device_id = None

        # Attempt to extract device_id from /devices/<id>/...
        if "devices" in parts:
            try:
                idx = parts.index("devices")
                device_id = parts[idx + 1]
            except Exception:
                device_id = None
        else:
            # Global cmd topic: rely on payload
            device_id = payload.get("device_id")
            if not device_id and "sysid" in payload:
                try:
                    device_id = self.registry.device_id_for_mav(int(payload.get("sysid")))
                except Exception:
                    device_id = None

        # Determine transports to send to.
        # If we have an explicit device_id but no transports are known for it,
        # don't broadcast to all transports (that can cause commands to go to
        # a default sysid on a serial/udp transport). Instead warn and skip.
        if device_id:
            target_transports = self.registry.transports_for(device_id)
            if not target_transports:
                print(f"[WARN] No transports known for device_id={device_id}; skipping command until device is discovered")
                return
        else:
            # No device_id known -> broadcast to all transports
            target_transports = set(self.transports.keys())

        # If topic looks like a mission upload endpoint, prefer a well-known msg_type
            print(f"[DEBUG] on_cmd: topic={topic} device_id={device_id} is_mission_upload={is_mission_upload} payload={payload}")
        is_mission_upload = topic.endswith('/mission/upload') or '/mission/upload' in topic

        for tname in target_transports:
            t = self.transports.get(tname)
            if not t:
                continue
            pkt = Packet(
                device_id=device_id,
                schema=payload.get("schema", "mavlink"),
                msg_type=("MISSION_UPLOAD" if is_mission_upload else payload.get("msg_type", "raw")),
                fields=payload,
                timestamp=time.time(),
                origin="mqtt"
            )
            t.write(pkt)

    # --- internal workers ---
    def _proc_loop(self):
        while self._run:
            pkt = self.q.get()
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
            from wayfarer.core.publisher import publish_for_wayfarer
        except Exception:
            return False
        try:
            publish_for_wayfarer(retain=True)
            return True
        except Exception:
            return False
