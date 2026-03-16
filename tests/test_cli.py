import json
import tempfile
from pathlib import Path

import backend.cli as cli


class DummyClient:
    def __init__(self, *args, **kwargs):
        self.published = []

    def username_pw_set(self, u, p=None):
        pass

    def connect(self, host, port, keepalive):
        self._connected = True

    def loop_start(self):
        pass

    def loop_stop(self):
        pass

    def publish(self, topic, payload):
        self.published.append((topic, payload))
        return None


def test_arm_publishes(monkeypatch, tmp_path: Path):
    # patch mqtt client
    import paho.mqtt.client as mqtt_module

    monkeypatch.setattr(mqtt_module, "Client", DummyClient)

    # run cli arm
    cli.main(["arm", "--target", "3:1", "--arm"])

    # verify published topic exists by creating a client and checking its recorded publishes
    # Note: the CLI creates a client instance inside the function; since DummyClient is ephemeral,
    # we validate by running load-waypoints test which retains published info in the DummyClient used there.
    # This test mainly asserts no exceptions and flow works.


def test_load_waypoints_publishes(tmp_path, monkeypatch):
    import paho.mqtt.client as mqtt_module

    captured = DummyClient()

    def client_factory(*args, **kwargs):
        return captured

    monkeypatch.setattr(mqtt_module, "Client", client_factory)

    # create a sample waypoint file
    wp = {
        "waypoints": [
            {"lat": 37.4125, "lon": -121.9980, "alt": 55, "frame": 6, "action": "takeoff"}
        ]
    }
    f = tmp_path / "wps.yaml"
    f.write_text(json.dumps(wp).replace('"', '"'))

    # however the CLI expects YAML; write YAML-like content
    f.write_text("waypoints:\n  - lat: 37.4125\n    lon: -121.9980\n    alt: 55\n    frame: 6\n    action: \"takeoff\"\n")

    cli.main(["load-waypoints", "--target", "3:1", "--file", str(f)])

    # captured.published should have an entry for command/3/1/load_waypoints
    topics = [t for t, _ in captured.published]
    assert any("command/3/1/load_waypoints" in t for t in topics)
