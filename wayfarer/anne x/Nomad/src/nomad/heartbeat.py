"""Internal GCS heartbeat sender (multiprocessing).

Sends a periodic heartbeat packet to the router bind address so the router will
forward it to birds/GCS. The payload is a small JSON blob containing sysid and timestamp.
If `pymavlink` is installed this can be extended to send a real MAVLink heartbeat.
"""
import multiprocessing
import socket
import time
import json
import os
from typing import Tuple

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
LOG_DIR = os.path.join(BASE_DIR, "logs")
os.makedirs(LOG_DIR, exist_ok=True)


def _hb_loop(target: Tuple[str, int], sysid: int, interval: float, stop_event):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(1.0)
    while not stop_event.is_set():
        payload = {"type": "HEARTBEAT", "sysid": sysid, "ts": time.time()}
        data = json.dumps(payload).encode()
        try:
            sock.sendto(data, target)
        except Exception:
            # best-effort
            pass

        # also append to a heartbeat log for visibility
        try:
            with open(os.path.join(LOG_DIR, f"internal_gcs_{sysid}_hb.log"), "a") as fh:
                fh.write(json.dumps(payload) + "\n")
        except Exception:
            pass

        stop_event.wait(interval)


class HeartbeatSender:
    def __init__(self, target: Tuple[str, int], sysid: int = 250, interval: float = 1.0):
        self.target = target
        self.sysid = sysid
        self.interval = interval
        self.process: multiprocessing.Process = None
        self._stop_event = None

    def start(self):
        if self.process and self.process.is_alive():
            return
        self._stop_event = multiprocessing.Event()
        self.process = multiprocessing.Process(target=_hb_loop, args=(self.target, self.sysid, self.interval, self._stop_event), daemon=True)
        self.process.start()

    def stop(self, timeout: float = 2.0):
        if not self.process:
            return
        if not self.process.is_alive():
            return
        try:
            self._stop_event.set()
        except Exception:
            pass
        self.process.join(timeout)


if __name__ == "__main__":
    # quick test runner
    target = ("127.0.0.1", 14540)
    hb = HeartbeatSender(target, sysid=250, interval=1.0)
    hb.start()
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        hb.stop()
