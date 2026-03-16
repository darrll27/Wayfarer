import os
import time
import json
import pytest
import paho.mqtt.client as mqtt

from . import reporter
from .mission_utils import canonicalize_mission, hash_mission


def test_mission_upload_mqtt():
    """Test mission upload via MQTT interface, simulating vehicle responses."""
    test_name = "test_mission_upload_mqtt"
    start = time.time()

    # Mission to upload
    mission = [
        {"seq": 0, "frame": 0, "command": 16, "lat": 11111111, "lon": 22222222, "alt": 10.0},
        {"seq": 1, "frame": 0, "command": 16, "lat": 33333333, "lon": 44444444, "alt": 20.0},
    ]

    # Canonicalize for hash
    uploaded = canonicalize_mission(mission)
    upl_hash = hash_mission(uploaded)

    client = mqtt.Client()
    received_acks = []
    received_requests = []
    received_acks_mission = []

    def on_connect(client, userdata, flags, rc):
        client.subscribe("command/1/1/ack")
        client.subscribe("device/1/1/MISSION_REQUEST")
        client.subscribe("device/1/1/MISSION_ACK")

    def on_message(client, userdata, msg):
        topic = msg.topic
        payload = json.loads(msg.payload.decode())
        if topic == "command/1/1/ack":
            received_acks.append(payload)
        elif "MISSION_REQUEST" in topic:
            received_requests.append(payload)
        elif "MISSION_ACK" in topic:
            received_acks_mission.append(payload)

    client.on_connect = on_connect
    client.on_message = on_message

    try:
        client.connect("127.0.0.1", 1883, 60)
        client.loop_start()

        # Wait for connection
        time.sleep(1)

        # Send load_waypoints
        load_payload = {
            "action": "load_waypoints",
            "waypoints": mission,
            "filename": "test_mission.yaml"
        }
        client.publish("command/1/1/load_waypoints", json.dumps(load_payload))

        # Wait for validation ack
        timeout = 5
        start_wait = time.time()
        while time.time() - start_wait < timeout and not received_acks:
            time.sleep(0.1)

        assert received_acks, "No validation ack received"
        ack = received_acks[0]
        assert ack.get("status") == "validated and uploading", f"Unexpected ack: {ack}"

        # Simulate vehicle responses
        # Wait for MISSION_REQUESTs
        start_wait = time.time()
        while time.time() - start_wait < timeout and len(received_requests) < 2:
            time.sleep(0.1)

        assert len(received_requests) == 2, f"Expected 2 MISSION_REQUESTs, got {len(received_requests)}"

        # Send MISSION_ACK
        ack_payload = {"fields": {}}
        client.publish("device/1/1/MISSION_ACK", json.dumps(ack_payload))

        # Wait for completion
        start_wait = time.time()
        while time.time() - start_wait < timeout and not received_acks_mission:
            time.sleep(0.1)

        assert received_acks_mission, "No MISSION_ACK received"

        duration = time.time() - start
        reporter.write_report(test_name, "PASS", details=f"mission_hash={upl_hash}", duration=duration)

    except Exception as e:
        duration = time.time() - start
        reporter.write_report(test_name, "FAIL", details=str(e), duration=duration)
        raise
    finally:
        client.loop_stop()
        client.disconnect()


if __name__ == "__main__":
    test_mission_upload_mqtt()
    print("MQTT upload test completed")