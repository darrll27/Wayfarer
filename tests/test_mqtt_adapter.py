import json
import queue
import sys
import types


def _install_paho_stub():
    if "paho.mqtt.client" in sys.modules:
        return
    paho = types.ModuleType("paho")
    mqtt_pkg = types.ModuleType("paho.mqtt")
    client_mod = types.ModuleType("paho.mqtt.client")

    class FakePahoClient:
        def __init__(self, *args, **kwargs):
            pass

        def username_pw_set(self, *args, **kwargs):
            pass

        def publish(self, *args, **kwargs):
            pass

        def subscribe(self, *args, **kwargs):
            pass

    client_mod.Client = FakePahoClient
    sys.modules["paho"] = paho
    sys.modules["paho.mqtt"] = mqtt_pkg
    sys.modules["paho.mqtt.client"] = client_mod


_install_paho_stub()

from backend.mav_router.mqtt_adapter import MQTTAdapter


class DummyClient:
    def __init__(self):
        self.publishes = []
        self.subscriptions = []

    def publish(self, topic, payload=None):
        self.publishes.append((topic, payload))

    def subscribe(self, topic):
        self.subscriptions.append(topic)


class DummyMsg:
    def __init__(self, topic, payload_bytes):
        self.topic = topic
        self.payload = payload_bytes


def make_adapter():
    cfg = {"mqtt": {"host": "localhost", "port": 1883}, "command_out_port": "udp1"}
    # one fake port with an out_q
    ports = {"udp1": {"out_q": queue.Queue()}}

    class DummyRouter:
        pass

    router = DummyRouter()
    router.observed_sysids = {"udp1": {1}}
    router.last_addr = {"udp1": ("127.0.0.1", 14550)}

    adapter = MQTTAdapter(cfg, ports, router, mqtt_pub_q=queue.Queue())
    # replace real mqtt client with dummy
    adapter.client = DummyClient()
    return adapter, ports


def make_adapter_with_forced_command_port():
    cfg = {"mqtt": {"host": "localhost", "port": 1883}, "command_out_port": "bridge_out"}
    ports = {
        "udp1": {"out_q": queue.Queue()},
        "bridge_out": {"out_q": queue.Queue()},
    }

    class DummyRouter:
        pass

    router = DummyRouter()
    router.observed_sysids = {"udp1": {1}, "bridge_out": set()}
    router.last_addr = {
        "udp1": ("127.0.0.1", 14550),
        "bridge_out": ("127.0.0.1", 14551),
    }

    adapter = MQTTAdapter(cfg, ports, router, mqtt_pub_q=queue.Queue())
    adapter.client = DummyClient()
    return adapter, ports


def test_command_long_encoding_and_ack():
    adapter, ports = make_adapter()

    payload = {
        "msg": "COMMAND_LONG",
        "target_sys": 1,
        "target_comp": 1,
        "command": 176,
        "params": [0, 0, 0, 0, 0, 0, 0],
    }

    msg = DummyMsg("command/1/1/details", json.dumps(payload).encode("utf-8"))
    adapter.on_message(None, None, msg)

    # outbound bytes should be in the port's out_q
    out_addr, out_bytes = ports["udp1"]["out_q"].get_nowait()
    assert out_addr == ("127.0.0.1", 14550)
    assert isinstance(out_bytes, (bytes, bytearray))
    # ACK should have been published
    assert any(p[0] == "command/1/1/ack" for p in adapter.client.publishes)


def test_mission_item_int_encoding_and_ack():
    adapter, ports = make_adapter()

    payload = {
        "msg": "MISSION_ITEM_INT",
        "target_sys": 1,
        "target_comp": 1,
        "seq": 0,
        "frame": 0,
        "command": 16,
        "x": 0,
        "y": 0,
        "z": 10.0,
        "params": [0, 0, 0, 0],
    }
    msg = DummyMsg("command/1/1/details", json.dumps(payload).encode("utf-8"))
    adapter.on_message(None, None, msg)

    out_addr, out_bytes = ports["udp1"]["out_q"].get_nowait()
    assert out_addr == ("127.0.0.1", 14550)
    assert isinstance(out_bytes, (bytes, bytearray))
    assert any(p[0] == "command/1/1/ack" for p in adapter.client.publishes)


def test_frontend_mav_cmd_name_encodes_command_long():
    adapter, ports = make_adapter()

    payload = {
        "command": "MAV_CMD_COMPONENT_ARM_DISARM",
        "params": [1, 0, 0, 0, 0, 0, 0],
        "src_sysid": 250,
        "src_compid": 1,
    }

    msg = DummyMsg("command/1/1/details", json.dumps(payload).encode("utf-8"))
    adapter.on_message(None, None, msg)

    out_addr, out_bytes = ports["udp1"]["out_q"].get_nowait()
    assert out_addr == ("127.0.0.1", 14550)
    # COMMAND_LONG should be packed MAVLink, not JSON fallback bytes.
    assert out_bytes[0] in (0xFE, 0xFD)
    assert any(p[0] == "command/1/1/ack" for p in adapter.client.publishes)


def test_command_long_uses_forced_command_out_port():
    adapter, ports = make_adapter_with_forced_command_port()

    payload = {
        "command": "MAV_CMD_COMPONENT_ARM_DISARM",
        "params": [1, 0, 0, 0, 0, 0, 0],
    }

    msg = DummyMsg("command/1/1/details", json.dumps(payload).encode("utf-8"))
    adapter.on_message(None, None, msg)

    out_addr, out_bytes = ports["bridge_out"]["out_q"].get_nowait()
    assert out_addr == ("127.0.0.1", 14551)
    assert out_bytes[0] in (0xFE, 0xFD)
    assert ports["udp1"]["out_q"].empty()


def test_on_connect_subscribes_to_mission_download_topics():
    adapter, _ = make_adapter()
    client = DummyClient()

    adapter.on_connect(client, None, None, 0)

    assert "device/+/+/MISSION_COUNT" in client.subscriptions
    assert "device/+/+/MISSION_ITEM_INT" in client.subscriptions


def test_labeled_device_topics_drive_mission_handlers():
    adapter, _ = make_adapter()
    calls = []
    adapter.mission_manager.handle_mission_count = lambda sysid, compid, count: calls.append(("count", sysid, compid, count))
    adapter.mission_manager.handle_mission_item = lambda sysid, compid, seq, item: calls.append(("item", sysid, compid, seq, item["command"]))

    count_msg = DummyMsg("device/sysid_7/compid_1/MISSION_COUNT", json.dumps({"fields": {"count": 2}}).encode("utf-8"))
    item_msg = DummyMsg(
        "device/sysid_7/compid_1/MISSION_ITEM_INT",
        json.dumps({"fields": {"seq": 1, "frame": 0, "command": 16, "x": 1, "y": 2, "z": 3}}).encode("utf-8"),
    )

    adapter.on_message(None, None, count_msg)
    adapter.on_message(None, None, item_msg)

    assert ("count", 7, 1, 2) in calls
    assert ("item", 7, 1, 1, 16) in calls
