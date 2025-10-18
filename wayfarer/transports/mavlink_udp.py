import time, threading, queue
from typing import Optional
from pymavlink import mavutil
from wayfarer.core.packet import Packet

class MavlinkUDP:
    def __init__(self, name: str, endpoint: str, on_discover, on_packet):
        self.name = name
        self.endpoint = endpoint
        self.on_discover = on_discover   # (sysid, transport_name) -> device_id
        self.on_packet = on_packet       # (Packet) -> None
        self._conn = None
        self._txq = queue.Queue(maxsize=1024)
        self._run = False

    def start(self):
        self._conn = mavutil.mavlink_connection(self.endpoint)
        self._run = True
        threading.Thread(target=self._rx_loop, daemon=True).start()
        threading.Thread(target=self._tx_loop, daemon=True).start()

    def stop(self):
        self._run = False
        try:
            self._conn.close()
        except Exception:
            pass

    def _rx_loop(self):
        while self._run:
            try:
                msg = self._conn.recv_match(blocking=True, timeout=0.1)
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
                # swallow to keep daemon alive; production: log error
                pass

    def _tx_loop(self):
        while self._run:
            try:
                pkt = self._txq.get(timeout=0.1)
                # Expect raw mavlink command payloads under pkt.fields["raw"]
                raw = pkt.fields.get("raw")
                if raw and isinstance(raw, (bytes, bytearray)):
                    self._conn.write(raw)
                # Future: map normalized commands -> mavlink pack + send
            except queue.Empty:
                continue
            except Exception:
                pass

    def write(self, pkt: Packet):
        # enqueue for send
        try:
            self._txq.put_nowait(pkt)
        except Exception:
            pass
