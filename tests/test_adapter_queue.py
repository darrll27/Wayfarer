import json
import queue
import threading
import time

from backend.mav_router.mqtt_adapter import MQTTAdapter


class DummyClient:
    def __init__(self):
        self.publishes = []

    def publish(self, topic, payload=None):
        self.publishes.append((topic, payload))

    def subscribe(self, topic):
        pass


class DummyMsg:
    def __init__(self, topic, payload_bytes):
        self.topic = topic
        self.payload = payload_bytes


def make_adapter_no_start():
    cfg = {"mqtt": {"host": "localhost", "port": 1883}}
    ports = {"udp1": {"out_q": queue.Queue()}}

    class DummyRouter:
        pass

    router = DummyRouter()
    # initially, no observed sysids
    router.observed_sysids = {"udp1": set()}
    router.last_addr = {}

    adapter = MQTTAdapter(cfg, ports, router, mqtt_pub_q=queue.Queue())
    adapter.client = DummyClient()
    return adapter, ports, router


def test_pending_delivery_after_router_observed():
    adapter, ports, router = make_adapter_no_start()

    # start the pending loop in a separate daemon thread
    th = threading.Thread(target=adapter._pending_loop, daemon=True)
    th.start()

    # publish a command for target sys 42 which is not yet observed
    payload = {"msg": "COMMAND_LONG", "target_sys": 42, "target_comp": 1, "command": 176, "params": [0]*7}
    msg = DummyMsg("command/42/1/details", json.dumps(payload).encode("utf-8"))
    adapter.on_message(None, None, msg)

    # ensure it was queued
    assert 42 in adapter.pending_commands

    # now simulate the router observing sysid 42 on udp1
    router.observed_sysids["udp1"].add(42)
    router.last_addr["udp1"] = ("127.0.0.1", 14550)

    # allow pending loop to run and deliver
    time.sleep(1.0)

    # verify delivery into out_q
    out_addr, out_bytes = ports["udp1"]["out_q"].get_nowait()
    assert out_addr == ("127.0.0.1", 14550)
    assert isinstance(out_bytes, (bytes, bytearray))
    # ACK should have been published indicating delivery
    assert any(p[0].startswith("command/42/") and "delivered" in str(p[1]) for p in adapter.client.publishes)
