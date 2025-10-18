import json
import threading
import paho.mqtt.client as mqtt

class MQTTRouter:
    def __init__(self, name: str, cfg: dict, on_cmd: callable):
        self.name = name
        self.cfg = cfg
        self.on_cmd = on_cmd
        self._client = mqtt.Client(client_id=cfg.get("client_id","wayfarer"))
        self._client.on_message = self._on_message
        self._lock = threading.Lock()

    def start(self):
        self._client.connect(self.cfg["host"], int(self.cfg.get("port",1883)))
        self._client.loop_start()

    def stop(self):
        self._client.loop_stop()
        self._client.disconnect()

    def publish_telem(self, topic: str, payload: dict, qos: int = 0, retain: bool = False):
        data = json.dumps(payload, separators=(",",":"))
        with self._lock:
            self._client.publish(topic, data, qos=qos, retain=retain)

    def subscribe_cmd(self, topic: str):
        self._client.subscribe(topic)

    def _on_message(self, _client, _userdata, msg):
        # delegate to core for routing to transports
        self.on_cmd(msg.topic, msg.payload)
