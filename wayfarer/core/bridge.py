import json, time, threading
from queue import Queue
from wayfarer.core.registry import DeviceRegistry
from wayfarer.core.constants import (
    TOPIC_VERSION, DISCOVERY_TOPIC, HEARTBEAT_TOPIC, RAW_MAVLINK_TOPIC,
    CMD_WILDCARD
)
from wayfarer.core.packet import Packet
from wayfarer.core.router import RouteTable
from wayfarer.core.utils import safe_json

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
        # start MQTT and subscribe to command wildcard
        self.mqtt.start()
        self.mqtt.subscribe_cmd(CMD_WILDCARD.format(root=self.root))
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
        return device_id

    def on_transport_packet(self, pkt: Packet):
        # enqueue for processing -> MQTT publish
        try:
            self.q.put_nowait(pkt)
        except Exception:
            pass

    # --- MQTT -> transports (commands) ---
    def on_cmd(self, topic: str, data: bytes):
        # topic: wayfarer/v1/devices/<id>/cmd/...
        try:
            payload = json.loads(data.decode("utf-8"))
        except Exception:
            return
        parts = topic.split("/")
        try:
            idx = parts.index("devices")
            device_id = parts[idx+1]
        except Exception:
            return
        # broadcast to all transports that have seen this device
        for tname in self.registry.transports_for(device_id) or self.transports.keys():
            t = self.transports.get(tname)
            if not t: continue
            pkt = Packet(
                device_id=device_id, schema=payload.get("schema","mavlink"),
                msg_type=payload.get("msg_type","raw"), fields=payload, timestamp=time.time(),
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
                            "t": pkt.timestamp
                        }
                    )

    def _heartbeat_loop(self):
        interval = float(self.cfg.get("mqtt",{}).get("heartbeat_secs", 2.0))
        while self._run:
            snap = self.registry.snapshot()
            for device_id in snap.keys():
                topic = HEARTBEAT_TOPIC.format(root=self.root, device_id=device_id)
                self.mqtt.publish_telem(topic, {"status":"online","ts":time.time()}, retain=True)
            time.sleep(interval)
