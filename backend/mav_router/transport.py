"""Thin transport layer: one process per port with inbound/outbound queues.

Supports UDP and Serial transports. Each transport process puts tuples into a
central router inbound queue: (port_name, src_addr, data_bytes).

Outbound messages are taken from a per-port outbound queue as tuples
(dest_addr, data_bytes) where dest_addr is an (ip,port) for UDP and ignored for serial.
"""
from __future__ import annotations

import json
import os
import socket
import time
import threading
from multiprocessing import Queue
from typing import Tuple, Optional

try:
    import serial
except Exception:
    serial = None  # pyserial optional; errors raised when attempting serial transport

try:
    from pymavlink import mavutil
    _MAVLINK_AVAILABLE = True
except Exception:
    mavutil = None
    _MAVLINK_AVAILABLE = False


def _open_packet_logs(name: str):
    if os.environ.get("NOMAD_PACKET_LOG") != "1":
        return None, None
    log_dir = os.environ.get("NOMAD_LOG_DIR", "logs")
    os.makedirs(log_dir, exist_ok=True)
    raw_path = os.path.join(log_dir, f"udp_packets_{name}.raw.log")
    decoded_path = os.path.join(log_dir, f"udp_packets_{name}.decoded.log")
    raw_f = open(raw_path, "a", buffering=1)
    decoded_f = open(decoded_path, "a", buffering=1) if os.environ.get("NOMAD_PACKET_DECODE") == "1" else None
    return raw_f, decoded_f


def _log_raw(raw_f, direction: str, name: str, addr, data: bytes):
    if not raw_f:
        return
    entry = {
        "ts": time.time(),
        "dir": direction,
        "port": name,
        "addr": addr,
        "len": len(data),
        "hex": data.hex(),
    }
    raw_f.write(json.dumps(entry) + "\n")


def _log_decoded(decoded_f, parser, direction: str, name: str, addr, data: bytes):
    if not decoded_f or not parser:
        return
    try:
        for b in data:
            msg = parser.parse_char(bytes([b]))
            if msg:
                entry = {
                    "ts": time.time(),
                    "dir": direction,
                    "port": name,
                    "addr": addr,
                    "type": msg.get_type(),
                    "fields": msg.to_dict(),
                }
                decoded_f.write(json.dumps(entry) + "\n")
    except Exception:
        pass


def udp_port_process(name: str, bind_addr: Tuple[str, int], router_in_q: Queue, port_out_q: Queue, mqtt_pub_q: Optional[Queue] = None, recv_buf: int = 4096):
    """Process loop for a UDP port. Blocks on socket recv and polls out queue periodically.

    Emits into router_in_q: (port_name, src_addr, data_bytes)
    Consumes from port_out_q: (dest_addr, data_bytes)
    """
    debug = os.environ.get("NOMAD_UDP_DEBUG") == "1"
    raw_f, decoded_f = _open_packet_logs(name)
    parser = mavutil.mavlink.MAVLink(None) if _MAVLINK_AVAILABLE and decoded_f else None
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    # Expand OS receive buffer to 4MB to absorb bursts from many drones
    _rcvbuf = 4 * 1024 * 1024
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, _rcvbuf)
        actual = sock.getsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF)
        print(f"[transport:{name}] SO_RCVBUF requested={_rcvbuf} actual={actual}")
    except Exception as e:
        print(f"[transport:{name}] could not set SO_RCVBUF: {e}")
    sock.bind(bind_addr)
    sock.settimeout(0.5)
    print(f"[transport:{name}] listening UDP {bind_addr}")
    # Use non-blocking mode to drain all queued packets per iteration
    sock.setblocking(False)
    try:
        while True:
            # Drain all available inbound packets before handling outbound
            got_any = False
            while True:
                try:
                    data, addr = sock.recvfrom(recv_buf)
                    if data:
                        got_any = True
                        if debug:
                            print(f"[transport:{name}] recv {len(data)} bytes from {addr}")
                        _log_raw(raw_f, "in", name, addr, data)
                        _log_decoded(decoded_f, parser, "in", name, addr, data)
                        router_in_q.put((name, addr, data))
                        if mqtt_pub_q is not None:
                            try:
                                mqtt_pub_q.put_nowait((name, addr, data))
                            except Exception:
                                pass
                except BlockingIOError:
                    break
                except Exception:
                    break

            # check outbound queue
            try:
                while not port_out_q.empty():
                    dest, outb = port_out_q.get_nowait()
                    if dest is None:
                        continue
                    try:
                        if debug:
                            print(f"[transport:{name}] send {len(outb)} bytes to {dest}")
                        _log_raw(raw_f, "out", name, dest, outb)
                        _log_decoded(decoded_f, parser, "out", name, dest, outb)
                        sock.sendto(outb, dest)
                    except Exception:
                        pass
            except Exception:
                pass

            # Brief yield so other threads can run; no sleep when packets are flowing
            if not got_any:
                time.sleep(0.001)
    except KeyboardInterrupt:
        print(f"[transport:{name}] stopping")
    finally:
        try:
            if raw_f:
                raw_f.close()
            if decoded_f:
                decoded_f.close()
        except Exception:
            pass
        sock.close()


def udp_send_process(name: str, port_out_q: Queue):
    """Send-only UDP loop. Emits data from out_q to dest_addr without binding a fixed port."""
    debug = os.environ.get("NOMAD_UDP_DEBUG") == "1"
    raw_f, decoded_f = _open_packet_logs(name)
    parser = mavutil.mavlink.MAVLink(None) if _MAVLINK_AVAILABLE and decoded_f else None
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(0.5)
    print(f"[transport:{name}] send-only UDP (ephemeral bind)")
    try:
        while True:
            try:
                while not port_out_q.empty():
                    dest, outb = port_out_q.get_nowait()
                    if dest is None:
                        continue
                    try:
                        if debug:
                            print(f"[transport:{name}] send {len(outb)} bytes to {dest}")
                        _log_raw(raw_f, "out", name, dest, outb)
                        _log_decoded(decoded_f, parser, "out", name, dest, outb)
                        sock.sendto(outb, dest)
                    except Exception:
                        pass
            except Exception:
                pass
            time.sleep(0.001)
    except KeyboardInterrupt:
        print(f"[transport:{name}] stopping")
    finally:
        try:
            if raw_f:
                raw_f.close()
            if decoded_f:
                decoded_f.close()
        except Exception:
            pass
        sock.close()


class UDPPort:
    def __init__(self, name: str, host: str, port: int, router_in_q: Queue, mqtt_pub_q: Optional[Queue] = None):
        self.name = name
        self.bind = (host, port)
        self.router_in_q = router_in_q
        self.out_q: Queue = Queue()
        self.thread: Optional[threading.Thread] = None
        self.mqtt_pub_q = mqtt_pub_q

    def start(self):
        self.thread = threading.Thread(target=udp_port_process, args=(self.name, self.bind, self.router_in_q, self.out_q, self.mqtt_pub_q))
        self.thread.daemon = True
        self.thread.start()
        return self.thread

    def stop(self):
        if self.thread is not None:
            # For threads, we can't "terminate" like processes, but we can set a flag or just let it finish
            # Since these are daemon threads, they'll be cleaned up when the main process exits
            pass


class UDPSendPort:
    def __init__(self, name: str):
        self.name = name
        self.out_q: Queue = Queue()
        self.thread: Optional[threading.Thread] = None

    def start(self):
        self.thread = threading.Thread(target=udp_send_process, args=(self.name, self.out_q))
        self.thread.daemon = True
        self.thread.start()
        return self.thread

    def stop(self):
        pass


def serial_port_process(name: str, device: str, baud: int, router_in_q: Queue, port_out_q: Queue, mqtt_pub_q: Optional[Queue] = None, read_size: int = 1024):
    """Process loop for a serial device. Retries open on failure.

    Emits into router_in_q: (port_name, src_addr, data_bytes)
    Consumes from port_out_q: (dest_addr, data_bytes) where dest_addr is ignored for serial
    """
    if serial is None:
        print(f"[transport:{name}] pyserial not installed; serial transport unavailable")
        return

    ser = None
    consecutive_errors = 0
    max_consecutive_errors = 5  # Only reopen after multiple consecutive errors

    while True:
        try:
            if ser is None:
                ser = serial.Serial(device, baudrate=baud, timeout=0.1)  # Shorter timeout
                print(f"[transport:{name}] opened serial {device} @ {baud}")
                consecutive_errors = 0

            # Try to read data
            try:
                data = ser.read(read_size)
                if data:
                    router_in_q.put((name, ("serial", device), data))
                    if mqtt_pub_q is not None:
                        try:
                            mqtt_pub_q.put_nowait((name, ("serial", device), data))
                        except Exception:
                            pass
                    consecutive_errors = 0  # Reset error count on successful read
                else:
                    # No data read, but that's normal - don't count as error
                    pass
            except Exception as e:
                consecutive_errors += 1
                print(f"[transport:{name}] read error (#{consecutive_errors}): {e}")
                if consecutive_errors >= max_consecutive_errors:
                    print(f"[transport:{name}] too many consecutive errors, reopening serial port")
                    try:
                        ser.close()
                    except Exception:
                        pass
                    ser = None
                    time.sleep(1.0)  # Wait before reopening
                    continue

            # handle outbound queue
            try:
                while not port_out_q.empty():
                    _, outb = port_out_q.get_nowait()
                    try:
                        ser.write(outb)
                    except Exception as e:
                        print(f"[transport:{name}] write error: {e}")
                        consecutive_errors += 1
                        if consecutive_errors >= max_consecutive_errors:
                            try:
                                ser.close()
                            except Exception:
                                pass
                            ser = None
                            break
            except Exception:
                pass

            time.sleep(0.001)
        except Exception as e:
            print(f"[transport:{name}] serial port error: {e}")
            if ser is not None:
                try:
                    ser.close()
                except Exception:
                    pass
                ser = None
            time.sleep(2.0)  # Wait before retrying

    # Cleanup
    try:
        if ser is not None:
            ser.close()
    except Exception:
        pass


class SerialPort:
    def __init__(self, name: str, device: str, baud: int, router_in_q: Queue, mqtt_pub_q: Optional[Queue] = None):
        self.name = name
        self.device = device
        self.baud = baud
        self.router_in_q = router_in_q
        self.out_q: Queue = Queue()
        self.thread: Optional[threading.Thread] = None
        self.mqtt_pub_q = mqtt_pub_q

    def start(self):
        self.thread = threading.Thread(target=serial_port_process, args=(self.name, self.device, self.baud, self.router_in_q, self.out_q, self.mqtt_pub_q))
        self.thread.daemon = True
        self.thread.start()
        return self.thread

    def stop(self):
        if self.thread is not None:
            # For threads, we can't "terminate" like processes, but we can set a flag or just let it finish
            # Since these are daemon threads, they'll be cleaned up when the main process exits
            pass


__all__ = ["udp_port_process", "udp_send_process", "UDPPort", "UDPSendPort", "serial_port_process", "SerialPort"]
