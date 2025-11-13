"""Thin transport layer: one process per port with inbound/outbound queues.

Supports UDP and Serial transports. Each transport process puts tuples into a
central router inbound queue: (port_name, src_addr, data_bytes).

Outbound messages are taken from a per-port outbound queue as tuples
(dest_addr, data_bytes) where dest_addr is an (ip,port) for UDP and ignored for serial.
"""
from __future__ import annotations

import socket
import time
from multiprocessing import Process, Queue
from typing import Tuple, Optional

try:
    import serial
except Exception:
    serial = None  # pyserial optional; errors raised when attempting serial transport


def udp_port_process(name: str, bind_addr: Tuple[str, int], router_in_q: Queue, port_out_q: Queue, mqtt_pub_q: Optional[Queue] = None, recv_buf: int = 4096):
    """Process loop for a UDP port. Blocks on socket recv and polls out queue periodically.

    Emits into router_in_q: (port_name, src_addr, data_bytes)
    Consumes from port_out_q: (dest_addr, data_bytes)
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(bind_addr)
    sock.settimeout(0.5)
    print(f"[transport:{name}] listening UDP {bind_addr}")
    try:
        while True:
            # receive
            try:
                data, addr = sock.recvfrom(recv_buf)
                if data:
                    router_in_q.put((name, addr, data))
                    # also publish a copy to mqtt publisher queue (non-blocking)
                    if mqtt_pub_q is not None:
                        try:
                            mqtt_pub_q.put_nowait((name, addr, data))
                        except Exception:
                            pass
            except socket.timeout:
                pass

            # check outbound queue
            try:
                while not port_out_q.empty():
                    dest, outb = port_out_q.get_nowait()
                    if dest is None:
                        # no destination specified, drop
                        continue
                    try:
                        sock.sendto(outb, dest)
                    except Exception:
                        # transient send failure; ignore
                        pass
            except Exception:
                # transient, continue loop
                pass

            time.sleep(0.001)
    except KeyboardInterrupt:
        print(f"[transport:{name}] stopping")
    finally:
        sock.close()


class UDPPort:
    def __init__(self, name: str, host: str, port: int, router_in_q: Queue, mqtt_pub_q: Optional[Queue] = None):
        self.name = name
        self.bind = (host, port)
        self.router_in_q = router_in_q
        self.out_q: Queue = Queue()
        self.process: Optional[Process] = None
        self.mqtt_pub_q = mqtt_pub_q

    def start(self):
        self.process = Process(target=udp_port_process, args=(self.name, self.bind, self.router_in_q, self.out_q, self.mqtt_pub_q))
        self.process.daemon = True
        self.process.start()
        return self.process

    def stop(self):
        if self.process is not None:
            self.process.terminate()
            self.process.join(timeout=1)


def serial_port_process(name: str, device: str, baud: int, router_in_q: Queue, port_out_q: Queue, mqtt_pub_q: Optional[Queue] = None, read_size: int = 1024):
    """Process loop for a serial device. Retries open on failure.

    Emits into router_in_q: (port_name, src_addr, data_bytes)
    Consumes from port_out_q: (dest_addr, data_bytes) where dest_addr is ignored for serial
    """
    if serial is None:
        print(f"[transport:{name}] pyserial not installed; serial transport unavailable")
        return

    ser = None
    while True:
        try:
            ser = serial.Serial(device, baudrate=baud, timeout=0.5)
            print(f"[transport:{name}] opened serial {device} @ {baud}")
            break
        except Exception as e:
            print(f"[transport:{name}] failed to open {device}: {e}; retrying in 2s")
            time.sleep(2.0)

    try:
        while True:
            try:
                data = ser.read(read_size)
                if data:
                    router_in_q.put((name, ("serial", device), data))
                    if mqtt_pub_q is not None:
                        try:
                            mqtt_pub_q.put_nowait((name, ("serial", device), data))
                        except Exception:
                            pass
            except Exception:
                # read error: try to reopen
                try:
                    ser.close()
                except Exception:
                    pass
                ser = None
                while True:
                    try:
                        ser = serial.Serial(device, baudrate=baud, timeout=0.5)
                        print(f"[transport:{name}] reopened serial {device}")
                        break
                    except Exception as e:
                        print(f"[transport:{name}] reopen failed: {e}; retrying in 2s")
                        time.sleep(2.0)

            # handle outbound queue
            try:
                while not port_out_q.empty():
                    _, outb = port_out_q.get_nowait()
                    try:
                        ser.write(outb)
                    except Exception:
                        # drop and attempt reopen next loop
                        break
            except Exception:
                pass

            time.sleep(0.001)
    except KeyboardInterrupt:
        print(f"[transport:{name}] stopping serial port")
    finally:
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
        self.process: Optional[Process] = None
        self.mqtt_pub_q = mqtt_pub_q

    def start(self):
        self.process = Process(target=serial_port_process, args=(self.name, self.device, self.baud, self.router_in_q, self.out_q, self.mqtt_pub_q))
        self.process.daemon = True
        self.process.start()
        return self.process

    def stop(self):
        if self.process is not None:
            self.process.terminate()
            self.process.join(timeout=1)


__all__ = ["udp_port_process", "UDPPort", "serial_port_process", "SerialPort"]
