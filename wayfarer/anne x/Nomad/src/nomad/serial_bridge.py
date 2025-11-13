"""Serial <-> UDP bridge for drones.

Supports URIs of the form:
- serial:///dev/ttyUSB0:57600
- udp://host:port

The bridge forwards raw bytes between a serial port and a UDP endpoint without
decoding MAVLink. Runs in its own process for isolation.
"""
import multiprocessing
import socket
import time
import os
from typing import Tuple

try:
    import serial
except Exception:
    serial = None

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
LOG_DIR = os.path.join(BASE_DIR, "logs")
os.makedirs(LOG_DIR, exist_ok=True)


def parse_serial_uri(uri: str) -> Tuple[str, int]:
    # expects '/dev/ttyUSB0:57600' or 'serial:///dev/ttyUSB0:57600'
    if uri.startswith("serial://"):
        uri = uri[len("serial://"):]
    if ":" not in uri:
        raise ValueError("serial uri must be path:baud")
    path, baud = uri.rsplit(":", 1)
    # Normalise common variants: allow 'serial://dev/..' (missing leading slash)
    # and ensure returned path is an absolute path
    if not path.startswith("/"):
        path = "/" + path
    return path, int(baud)


def parse_udp_uri(uri: str) -> Tuple[str, int]:
    if uri.startswith("udp://"):
        uri = uri[len("udp://"):]
    if ":" not in uri:
        raise ValueError("Invalid udp uri, expected host:port")
    host, port = uri.rsplit(":", 1)
    return host, int(port)


def _bridge_loop(serial_path: str, baud: int, udp_target: Tuple[str, int], udp_bind: Tuple[str, int] = ("0.0.0.0", 0)):
    # open serial
    if serial is None:
        # no pyserial available; log and exit
        try:
            logp = os.path.join(LOG_DIR, "serial_bridge_no_pyserial.log")
            with open(logp, "a") as fh:
                fh.write(f"Serial bridge requested for {serial_path}:{baud} but pyserial not installed\n")
        except Exception:
            pass
        return
    try:
        ser = serial.Serial(serial_path, baud, timeout=0.1)
    except Exception:
        # failed to open serial port; log the failure
        try:
            logp = os.path.join(LOG_DIR, "serial_bridge_open_errors.log")
            with open(logp, "a") as fh:
                fh.write(f"FAILED OPEN: serial={serial_path} baud={baud}\n")
        except Exception:
            pass
        return

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(udp_bind)
    sock.settimeout(0.1)

    # record startup details so operator knows which ports are in use
    try:
        info_path = os.path.join(LOG_DIR, f"serial_bridge_{os.path.basename(serial_path)}_{baud}.log")
        with open(info_path, "a") as fh:
            fh.write(f"BRIDGE START: serial={serial_path} baud={baud} udp_target={udp_target} udp_bind={udp_bind}\n")
    except Exception:
        pass

    while True:
        # read from serial -> send to udp
        try:
            data = ser.read(2048)
            if data:
                sock.sendto(data, udp_target)
        except Exception:
            pass

        # read from udp -> write to serial
        try:
            pdata, addr = sock.recvfrom(4096)
            if pdata:
                ser.write(pdata)
        except Exception:
            pass


class SerialBridge:
    def __init__(self, serial_uri: str, udp_target_uri: str):
        self.serial_uri = serial_uri
        self.udp_target_uri = udp_target_uri
        self.process: multiprocessing.Process = None

    def start(self):
        if self.process and self.process.is_alive():
            return
        spath, baud = parse_serial_uri(self.serial_uri)
        host, port = parse_udp_uri(self.udp_target_uri)
        # log and print which ports/uris are being used
        print(f"Starting serial bridge: serial={spath} baud={baud} -> udp={(host, port)}")
        try:
            info_path = os.path.join(LOG_DIR, f"serial_bridge_{os.path.basename(spath)}_{baud}_start.log")
            with open(info_path, "a") as fh:
                fh.write(f"Starting serial bridge: serial={spath} baud={baud} -> udp={(host, port)}\n")
        except Exception:
            pass
        self.process = multiprocessing.Process(target=_bridge_loop, args=(spath, baud, (host, port)), daemon=True)
        self.process.start()

    def stop(self, timeout: float = 2.0):
        if not self.process:
            return
        if not self.process.is_alive():
            return
        self.process.terminate()
        self.process.join(timeout)
