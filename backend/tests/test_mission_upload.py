import pytest
from unittest.mock import Mock, MagicMock
from multiprocessing import Queue
import yaml
from backend.mav_router.mqtt_adapter import MQTTAdapter
from backend.waypoint_validator.validator import validate_waypoints, waypoints_to_mission_items


def test_mission_upload_with_real_waypoints():
    """Test mission upload using real waypoint files from missions/demo/alpha/1_waypoints.yaml"""
    # Load real waypoints
    with open("missions/demo/alpha/1_waypoints.yaml", "r") as f:
        data = yaml.safe_load(f)
    
    waypoints = data["waypoints"]
    
    # Validate
    ok, details, norm = validate_waypoints(waypoints)
    assert ok, f"Validation failed: {details}"
    
    mission_items = waypoints_to_mission_items(norm)
    assert len(mission_items) == 4  # takeoff, 2 waypoints, land
    
    # Mock config
    cfg = {
        "mqtt": {"host": "localhost", "port": 1883},
        "gcs_sysid": 250,
        "gcs_compid": 190,
    }
    
    # Mock ports
    ports = {
        "drone_alpha_1": {"out_q": Queue()},
    }
    
    # Mock router
    router = Mock()
    router.observed_sysids = {"drone_alpha_1": {1}}
    router.last_addr = {"drone_alpha_1": ("127.0.0.1", 14560)}
    
    # Mock MQTT client
    mock_client = Mock()
    mqtt_pub_q = Queue()
    
    # Create adapter
    adapter = MQTTAdapter.__new__(MQTTAdapter)
    adapter.cfg = cfg
    adapter.ports = ports
    adapter.router = router
    adapter.mqtt_pub_q = mqtt_pub_q
    adapter.client = mock_client
    adapter.upload_states = {}
    
    # Start upload
    adapter._start_mission_upload(1, 1, mission_items)
    
    assert adapter.upload_states[1]['state'] == 'sending_items'
    assert len(adapter.upload_states[1]['mission']) == 4
    
    # Simulate all MISSION_REQUESTs
    for seq in range(4):
        adapter._handle_mission_request(1, 1, seq)
        # Check that packet was sent
        out_q = ports["drone_alpha_1"]["out_q"]
        assert not out_q.empty()
        addr, data = out_q.get()
        assert addr == ("127.0.0.1", 14560)
    
    # Simulate MISSION_ACK
    adapter._handle_mission_ack(1, 1)
    
    assert adapter.upload_states[1]['state'] == 'done'


if __name__ == "__main__":
    test_mission_upload_with_real_waypoints()
    print("Test passed!")