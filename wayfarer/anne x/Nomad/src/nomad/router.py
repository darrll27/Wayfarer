"""Multiprocessing UDP router for NOMAD.

Design:
- Router listens on a bind address and forwards every received UDP packet to all configured targets
  (except back to the original sender).
- Router does not decode MAVLink. It logs raw packets to `logs/` by source address.
- The router runs in a separate process (multiprocessing) to avoid GIL contention.
"""
import os
import socket
import multiprocessing
import time
from typing import List, Tuple

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
LOG_DIR = os.path.join(BASE_DIR, "logs")
os.makedirs(LOG_DIR, exist_ok=True)


def _sanitize_addr(addr: Tuple[str, int]) -> str:
    host, port = addr
    return f"{host.replace(':','_')}_{port}"


def _log_packet(src: Tuple[str, int], data: bytes) -> None:
    name = _sanitize_addr(src)
    path = os.path.join(LOG_DIR, f"{name}.log")
    try:
        with open(path, "ab") as fh:
            fh.write(b"---PACKET---\n")
            fh.write(f"from: {src}\n".encode())
            fh.write(data)
            fh.write(b"\n")
    except Exception:
        # best-effort logging
        pass


def parse_udp_uri(uri: str) -> Tuple[str, int]:
    """Parse 'udp://host:port' or 'host:port' into (host, int(port))."""
    if uri.startswith("udp://"):
        uri = uri[len("udp://"):]
    if ":" not in uri:
        raise ValueError("Invalid udp uri, expected host:port")
    host, port = uri.rsplit(":", 1)
    return host, int(port)


def _router_loop(bind: Tuple[str, int], targets: List[Tuple[str, int]], buffer_size: int = 2048):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(bind)
    # write an explicit start log with bind/targets so it's clear which ports are in use
    try:
        start_path = os.path.join(LOG_DIR, f"router_{bind[0].replace(':','_')}_{bind[1]}_start.log")
        with open(start_path, "a") as fh:
            fh.write(f"ROUTER START: bind={bind} targets={targets}\n")
    except Exception:
        pass
    sock.settimeout(0.5)
    while True:
        try:
            data, addr = sock.recvfrom(buffer_size)
        except socket.timeout:
            continue
        except Exception:
            break

        # log raw packet
        _log_packet(addr, data)

        # forward to targets except the sender if equal
        for tgt in targets:
            try:
                if addr[0] == tgt[0] and addr[1] == tgt[1]:
                    continue
                sock.sendto(data, tgt)
            except Exception:
                # ignore per-target failures; router is best-effort
                continue


class Router:
    def __init__(self, bind: Tuple[str, int], targets: List[Tuple[str, int]]):
        self.bind = bind
        self.targets = targets
        self.process: multiprocessing.Process = None

    def start(self):
        if self.process and self.process.is_alive():
            return
        # Log to stdout for developer visibility and to the logs dir
        print(f"Starting router process on bind={self.bind} -> targets={self.targets}")
        try:
            start_path = os.path.join(LOG_DIR, f"router_{self.bind[0].replace(':','_')}_{self.bind[1]}_start.log")
            with open(start_path, "a") as fh:
                fh.write(f"Starting router process on bind={self.bind} -> targets={self.targets}\n")
        except Exception:
            pass
        self.process = multiprocessing.Process(target=_router_loop, args=(self.bind, self.targets), daemon=True)
        self.process.start()

    def stop(self, timeout: float = 2.0):
        if not self.process:
            return
        if not self.process.is_alive():
            return
        self.process.terminate()
        self.process.join(timeout)


if __name__ == "__main__":
    # simple local test runner
    bind = ("0.0.0.0", 14540)
    targets = [("127.0.0.1", 14550), ("127.0.0.1", 14560)]
    r = Router(bind, targets)
    print(f"Starting router on {bind} -> {targets}")
    r.start()
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("Stopping router")
        r.stop()
