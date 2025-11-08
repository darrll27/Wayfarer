import time, threading, queue, logging
from typing import Optional
from pymavlink import mavutil
from wayfarer.core.packet import Packet
from wayfarer.core.command_mapper import send_command


class MavlinkGeneral:
    """
    Base MAVLink transport with queue-driven RX/TX threads and supervised connect/reconnect.
    Subclasses implement _open_connection() to create a pymavlink connection appropriate for
    their endpoint type (e.g., UDP vs Serial) while reusing the same I/O machinery.
    """

    def __init__(self, name: str, endpoint: str, on_discover, on_packet):
        self.name = name
        self.endpoint = endpoint
        self.on_discover = on_discover   # callable(sysid, transport_name) -> device_id
        self.on_packet = on_packet       # callable(Packet) -> None
        self._conn = None
        self._txq = queue.Queue(maxsize=1024)
        self._run = False
        self._connected = threading.Event()
        # Single I/O mutex ensures half-duplex access (either rx OR tx)
        self._io_lock = threading.Lock()
        # Optional source identity for outbound MAVLink frames
        self._source_sysid: Optional[int] = None
        self._source_compid: Optional[int] = None
        # Diagnostics
        self._conn_ts: Optional[float] = None
        self._last_heartbeat_ts: Optional[float] = None
        self._heartbeat_warned = False
        # track internal threads so we can join them on stop
        self._threads = []

    # ---- to be overridden by subclasses ----
    def _open_connection(self):
        """Create and return a pymavlink connection for this endpoint.
        Subclasses must implement.
        """
        raise NotImplementedError()

    # ---- common API ----
    def set_source_identity(self, sysid: Optional[int], compid: Optional[int]):
        if sysid is not None:
            self._source_sysid = int(sysid)
        if compid is not None:
            self._source_compid = int(compid)
        with self._io_lock:
            if self._conn:
                try:
                    if self._source_sysid is not None:
                        self._conn.source_system = self._source_sysid
                    if self._source_compid is not None:
                        self._conn.source_component = self._source_compid
                except Exception:
                    pass

    def start(self):
        self._run = True
        t = threading.Thread(target=self._connect_loop, daemon=False)
        t.start()
        self._threads.append(t)
        t = threading.Thread(target=self._rx_loop, daemon=False)
        t.start()
        self._threads.append(t)
        t = threading.Thread(target=self._tx_loop, daemon=False)
        t.start()
        self._threads.append(t)

    def stop(self):
        # Signal loops to stop
        self._run = False
        # Close connection under io lock to interrupt blocking recv/write
        try:
            with self._io_lock:
                if self._conn:
                    try:
                        self._conn.close()
                    except Exception:
                        pass
                self._conn = None
                self._connected.clear()
        except Exception:
            pass

        # Join worker threads with short timeout
        for thr in getattr(self, "_threads", []):
            try:
                thr.join(timeout=2.0)
            except Exception:
                pass

    # ---- loops ----
    def _connect_loop(self):
        while self._run:
            if self._conn is None:
                try:
                    logging.info(f"[mavlink:{self.name}] attempting open {self.endpoint}")
                    conn = self._open_connection()
                    # Apply configured source identity if provided
                    try:
                        if self._source_sysid is not None:
                            conn.source_system = self._source_sysid
                        if self._source_compid is not None:
                            conn.source_component = self._source_compid
                    except Exception:
                        pass
                    with self._io_lock:
                        self._conn = conn
                        self._connected.set()
                        self._conn_ts = time.time()
                        self._last_heartbeat_ts = None
                        self._heartbeat_warned = False
                    logging.info(f"[mavlink:{self.name}] connected/opened")
                except Exception as e:
                    logging.warning(f"[mavlink:{self.name}] open failed: {e}; retry in 1s")
                    time.sleep(1.0)
                    continue
            else:
                time.sleep(1.0)

    def _rx_loop(self):
        while self._run:
            if not self._connected.wait(timeout=0.2):
                continue
            try:
                with self._io_lock:
                    conn = self._conn
                    if not conn:
                        continue
                    msg = conn.recv_match(blocking=True, timeout=0.2)
                if not msg:
                    continue
                # Determine sysid/compid from message or connection
                sysid = getattr(msg, "get_srcSystem", lambda: None)() or conn.target_system or -1
                compid = getattr(msg, "get_srcComponent", lambda: None)() or conn.target_component or 0
                if sysid is None or int(sysid) < 0:
                    # Unknown sysid; skip publishing/discovery
                    continue
                # heartbeat tracking
                if msg.get_type() == "HEARTBEAT":
                    self._last_heartbeat_ts = time.time()
                if (not self._heartbeat_warned and self._conn_ts and self._last_heartbeat_ts is None and (time.time() - self._conn_ts) > 5.0):
                    logging.warning(f"[mavlink:{self.name}] no HEARTBEAT received >5s after connect; check endpoint={self.endpoint}")
                    self._heartbeat_warned = True

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
            except Exception as e:
                logging.warning(f"[mavlink:{self.name}] rx error: {e}; resetting connection")
                with self._io_lock:
                    if self._conn:
                        try:
                            self._conn.close()
                        except Exception:
                            pass
                    self._conn = None
                    self._connected.clear()

    def _tx_loop(self):
        while self._run:
            if not self._connected.wait(timeout=0.2):
                continue
            try:
                pkt = self._txq.get(timeout=0.2)
            except queue.Empty:
                continue
            try:
                with self._io_lock:
                    conn = self._conn
                    if not conn:
                        continue
                    raw = pkt.fields.get("raw")
                    if raw and isinstance(raw, (bytes, bytearray)):
                        conn.write(raw)
                    else:
                        send_command(conn, pkt)
            except Exception as e:
                logging.warning(f"[mavlink:{self.name}] tx error: {e}; resetting connection")
                with self._io_lock:
                    if self._conn:
                        try:
                            self._conn.close()
                        except Exception:
                            pass
                    self._conn = None
                    self._connected.clear()

    # --- API ---
    def write(self, pkt: Packet):
        try:
            self._txq.put_nowait(pkt)
        except Exception:
            pass
