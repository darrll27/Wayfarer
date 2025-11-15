import os
import time
import json
import pytest
import paho.mqtt.client as mqtt
import requests

from . import reporter
from .mission_utils import canonicalize_mission, hash_mission


def test_mission_api_flow():
    """Test full mission upload/download flow through API -> MQTT -> router."""
    test_name = "test_mission_api_flow"
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
    received_downloads = []

    def on_connect(client, userdata, flags, rc):
        client.subscribe("command/1/1/ack")
        client.subscribe("device/1/1/MISSION_REQUEST")
        client.subscribe("device/1/1/MISSION_ACK")
        client.subscribe("Nomad/missions/downloaded/+")

    def on_message(client, userdata, msg):
        topic = msg.topic
        payload = json.loads(msg.payload.decode())
        if topic == "command/1/1/ack":
            received_acks.append(payload)
        elif "MISSION_REQUEST" in topic:
            received_requests.append(payload)
        elif "MISSION_ACK" in topic:
            received_acks_mission.append(payload)
        elif topic.startswith("Nomad/missions/downloaded/"):
            received_downloads.append(payload)

    client.on_connect = on_connect
    client.on_message = on_message

    try:
        client.connect("127.0.0.1", 1883, 60)
        client.loop_start()

        # Wait for connection
        time.sleep(1)

        # Create demo waypoints via API
        response = requests.post("http://127.0.0.1:8000/api/waypoints/demo")
        assert response.status_code == 200
        demo_data = response.json()
        assert demo_data["ok"] is True
        demo_files = demo_data["files"]

        # Upload mission via API
        upload_payload = {
            "filename": "test_api_mission.yaml",
            "raw": f"""
waypoints:
{chr(10).join([f"  - lat: {wp['lat']}\n    lon: {wp['lon']}\n    alt: {wp['alt']}\n    frame: {wp['frame']}\n    action: {wp['command']}" for wp in mission])}
"""
        }
        response = requests.post("http://127.0.0.1:8000/api/waypoints/upload_raw", json=upload_payload)
        assert response.status_code == 200
        upload_data = response.json()
        assert upload_data["ok"] is True

        # Send mission to drone via API
        send_payload = {"sysid": 1, "compid": 1, "filename": "test_api_mission.yaml"}
        response = requests.post("http://127.0.0.1:8000/api/waypoints/send", json=send_payload)
        assert response.status_code == 200
        send_data = response.json()
        assert send_data["ok"] is True

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

        # Now test download via API
        download_payload = {"sysid": 1, "compid": 1}
        response = requests.post("http://127.0.0.1:8000/api/waypoints/download", json=download_payload)
        assert response.status_code == 200
        download_data = response.json()
        assert download_data["ok"] is True

        # Simulate vehicle responses for download
        # Send MISSION_COUNT
        count_payload = {"count": 2, "fields": {}}
        client.publish("device/1/1/MISSION_COUNT", json.dumps(count_payload))

        # Wait for MISSION_REQUEST_INT
        received_download_requests = []
        def on_message_download(client, userdata, msg):
            topic = msg.topic
            payload = json.loads(msg.payload.decode())
            if "MISSION_REQUEST_INT" in topic:
                received_download_requests.append(payload)

        # Temporarily add download message handler
        original_on_message = client.on_message
        client.on_message = on_message_download

        start_wait = time.time()
        while time.time() - start_wait < timeout and len(received_download_requests) < 2:
            time.sleep(0.1)

        assert len(received_download_requests) == 2, f"Expected 2 MISSION_REQUEST_INTs, got {len(received_download_requests)}"

        # Send mission items
        for i, wp in enumerate(mission):
            item_payload = {
                "seq": wp["seq"],
                "frame": wp["frame"],
                "command": wp["command"],
                "param1": 0, "param2": 0, "param3": 0, "param4": 0,
                "x": wp["lat"], "y": wp["lon"], "z": wp["alt"],
                "mission_type": 0, "fields": {}
            }
            client.publish("device/1/1/MISSION_ITEM_INT", json.dumps(item_payload))

        # Restore original message handler
        client.on_message = original_on_message

        # Wait for downloaded mission
        start_wait = time.time()
        while time.time() - start_wait < timeout and not received_downloads:
            time.sleep(0.1)

        assert received_downloads, "No downloaded mission received"
        downloaded = received_downloads[0]
        assert downloaded["sysid"] == 1
        assert downloaded["count"] == 2
        assert len(downloaded["mission"]) == 2

        duration = time.time() - start
        reporter.write_report(test_name, "PASS", details=f"upload_hash={upl_hash}, download_count={downloaded['count']}", duration=duration)

    except Exception as e:
        duration = time.time() - start
        reporter.write_report(test_name, "FAIL", details=str(e), duration=duration)
        raise
    finally:
        client.loop_stop()
        client.disconnect()


if __name__ == "__main__":
    test_mission_api_flow()
    print("API flow test completed")