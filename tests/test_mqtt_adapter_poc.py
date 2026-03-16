import json
import queue

from backend.mav_router import mavlink_encoder


def test_poc_json_to_bytes_queue():
    # simulate a JSON COMMAND_LONG payload and ensure encoded bytes are pushed to a queue
    payload = {"msg": "COMMAND_LONG", "target_sys": 1, "target_comp": 1, "command": 176, "params": [0,0,0,0,0,0,0]}
    b = mavlink_encoder.encode_command_long(payload["target_sys"], payload["target_comp"], payload["command"], payload["params"])
    assert isinstance(b, (bytes, bytearray))
    # push to a queue like the adapter would do
    q = queue.Queue()
    q.put((("127.0.0.1", 14550), b))
    addr, got = q.get_nowait()
    assert got == b
