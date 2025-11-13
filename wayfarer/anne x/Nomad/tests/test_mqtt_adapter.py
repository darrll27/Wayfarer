import json
import queue

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
    cfg = {"mqtt": {"host": "localhost", "port": 1883}}
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
