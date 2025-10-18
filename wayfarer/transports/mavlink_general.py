import time, threading, queue
from typing import Optional
from pymavlink import mavutil
from wayfarer.core.packet import Packet
from wayfarer.core.command_mapper import send_command


class MavlinkGeneral:
    """
    Generic MAVLink transport that accepts either UDP or Serial endpoints.

    Examples:
      - endpoint: "udp:0.0.0.0:14550"
      - endpoint: "serial:/dev/ttyUSB0:115200"
    """

    def __init__(self, name: str, endpoint: str, on_discover, on_packet):
        self.name = name
        self.endpoint = endpoint
        self.on_discover = on_discover   # callable(sysid, transport_name) -> device_id
        self.on_packet = on_packet       # callable(Packet) -> None
        self._conn = None
        self._txq = queue.Queue(maxsize=1024)
        self._run = False

    # --- lifecycle ---
    def start(self):
        # Support both udp:* and serial:* endpoints using pymavlink API
        if self.endpoint.startswith("serial:"):
            parts = self.endpoint.split(":")
            if len(parts) >= 3:
                port, baud = parts[1], int(parts[2])
            else:
                raise ValueError(f"Invalid serial endpoint: {self.endpoint}")
            self._conn = mavutil.mavlink_connection(port, baud=baud)
        else:
            # Treat everything else as a pymavlink URL (e.g., udp:0.0.0.0:14550)
            self._conn = mavutil.mavlink_connection(self.endpoint)

        self._run = True
        threading.Thread(target=self._rx_loop, daemon=True).start()
        threading.Thread(target=self._tx_loop, daemon=True).start()

    def stop(self):
        self._run = False
        try:
            if self._conn:
                self._conn.close()
        except Exception:
            pass

    # --- I/O loops ---
    def _rx_loop(self):
        while self._run:
            try:
                msg = self._conn.recv_match(blocking=True, timeout=0.2)
                if not msg:
                    continue
                sysid = getattr(msg, "get_srcSystem", lambda: None)() or self._conn.target_system or 0
                compid = getattr(msg, "get_srcComponent", lambda: None)() or self._conn.target_component or 0
                device_id = self.on_discover(sysid, self.name)
                pkt = Packet(
                    device_id=device_id,
                    schema="mavlink",
                    msg_type=msg.get_type(),
                    fields=msg.to_dict(),
                    timestamp=time.time(),
                    origin=self.name,
                )
                self.on_packet(pkt)
            except Exception:
                # keep loop alive; production would log
                pass

    def _tx_loop(self):
        while self._run:
            try:
                pkt = self._txq.get(timeout=0.2)
                # 1) raw bytes write
                raw = pkt.fields.get("raw")
                if raw and isinstance(raw, (bytes, bytearray)):
                    self._conn.write(raw)
                    continue
                # 2) structured mapping
                send_command(self._conn, pkt)
            except queue.Empty:
                continue
            except Exception:
                pass

    # --- API ---
    def write(self, pkt: Packet):
        try:
            self._txq.put_nowait(pkt)
        except Exception:
            pass
