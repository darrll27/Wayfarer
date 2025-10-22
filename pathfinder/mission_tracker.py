import time
import json
from helpers import write_yaml_log

class MissionTracker:
    """
    Simple tracker per Pathfinder instance. Records events per device (sysid),
    persists YAML logs under .logs/<device_id>.yaml and can publish current log.
    """
    def __init__(self, base_dir, publish_on_save=False):
        self.base_dir = base_dir
        self.publish_on_save = publish_on_save
        self._logs = {}  # device_id -> list of events

    def _device_id(self, sysid):
        return f"mav_sys{sysid}"

    def record_command(self, sysid, action, topic, payload):
        device_id = self._device_id(sysid)
        ev = {
            "ts": int(time.time()),
            "action": action,
            "topic": topic,
            "payload": payload
        }
        self._logs.setdefault(device_id, []).append(ev)
        # persist immediately
        path = write_yaml_log(self.base_dir, device_id, self._logs[device_id])
        return device_id, path

    def get_log(self, sysid):
        device_id = self._device_id(sysid)
        return self._logs.get(device_id, [])

    def publish_log(self, client, topic_prefix, sysid, qos=0, retain=True):
        device_id = self._device_id(sysid)
        topic = f"{topic_prefix}/devices/{device_id}/mission_log"
        payload = {"device_id": device_id, "log": self._logs.get(device_id, [])}
        # publish JSON log for easy consumption
        client.publish(topic, json.dumps(payload), qos=qos, retain=bool(retain))
        return topic
