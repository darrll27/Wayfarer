"""Router: consumes transport inbound queue and applies routing rules.

Routing rules implemented (early thin version):
- Parse MAVLink header (v1 & v2) to extract src sysid/compid.
- Maintain observed sysids per port to detect which ports are GCS (250-255).
- If message sysid < 250 (vehicle): forward only to ports that have seen a GCS sysid (250-255).
- If message sysid >= 250: forward to all ports except origin (broadcast among GCS and >250).

This module intentionally keeps the router stateless except for observed sysids
and last-seen addresses per transport port.
"""
from __future__ import annotations

import time
from multiprocessing import Queue
from typing import Dict, Tuple, Optional, Set, List, Any
import socket
import hashlib
import time


def parse_sysid_compid(pkt: bytes) -> Tuple[Optional[int], Optional[int]]:
    """Minimal MAVLink v1/v2 header parser to extract sysid, compid.

    Returns (sysid, compid) or (None, None) if parsing fails.
    """
    if not pkt or len(pkt) < 6:
        return None, None
    b0 = pkt[0]
    # MAVLink v1: 0xFE, header: [0]=0xFE, [1]=len, [2]=seq, [3]=sysid, [4]=compid
    if b0 == 0xFE and len(pkt) >= 6:
        sysid = pkt[3]
        compid = pkt[4]
        return sysid, compid
    # MAVLink v2: 0xFD, header: [0]=0xFD, [1]=len, [2]=incompat, [3]=compat, [4]=seq, [5]=sysid, [6]=compid
    if b0 == 0xFD and len(pkt) >= 7:
        sysid = pkt[5]
        compid = pkt[6]
        return sysid, compid
    return None, None


class Router:
    def __init__(self, ports: Dict[str, Dict], forwards: Optional[List[Dict[str, Any]]] = None, verbose: bool = False, dedupe_window: float = 0.2):
        """ports: mapping port_name -> { 'out_q': Queue }

        The transport layer shares a central router_in_q where it posts inbound messages
        as tuples: (port_name, src_addr, data_bytes)
        """
        self.ports = ports
        # map port_name -> set of observed sysids
        self.observed_sysids: Dict[str, Set[int]] = {name: set() for name in ports.keys()}
        # last seen addr per port (for UDP send)
        self.last_addr: Dict[str, Tuple[str, int]] = {}
        # forwarding rules: list of dicts, see config guidance
        self.forwards = forwards or []
        self.verbose = bool(verbose)
        # small UDP socket for forwarding to arbitrary hosts
        try:
            self._udp_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        except Exception:
            self._udp_sock = None
        # dedupe recently forwarded packets to avoid loops: key -> last_time
        self._recent_forwarded = {}
        # dedupe recently seen packets globally to prevent re-processing same
        # packet many times when forwarding loops occur. Keyed by data digest -> last_time
        self._recent_seen = {}
        # how long to suppress re-processing of identical packets (seconds)
        self._dedupe_window = float(dedupe_window)

    def route_once(self, router_in_q: Queue, timeout: float = 0.5):
        try:
            item = router_in_q.get(timeout=timeout)
        except Exception:
            return
        port_name, src_addr, data = item
        sysid, compid = parse_sysid_compid(data)
        if sysid is not None:
            self.observed_sysids[port_name].add(sysid)
            self.last_addr[port_name] = src_addr

        # process configured forwards: mirror this inbound packet to configured targets
        if self.forwards and data:
            # global dedupe: skip heavy forwarding logic if we've seen this packet recently
            try:
                data_digest = hashlib.sha256(data).hexdigest()
                last_seen = self._recent_seen.get(data_digest)
                now = time.time()
                if last_seen and (now - last_seen) < self._dedupe_window:
                    if self.verbose:
                        try:
                            print(f"[router] global dedupe: skipping packet from {port_name} (digest={data_digest}) seen {now-last_seen:.3f}s ago")
                        except Exception:
                            pass
                    # still update last seen time
                    self._recent_seen[data_digest] = now
                    return
                # record seen
                self._recent_seen[data_digest] = now
            except Exception:
                pass
            # compute a short dedupe key to avoid re-forwarding same packet in tight loops
            try:
                digest = hashlib.sha256(data).hexdigest()[:16]
                fkey_prefix = f"{port_name}:{digest}"
            except Exception:
                fkey_prefix = f"{port_name}:{int(time.time())}"
            now = time.time()
            # iterate forwards matching this source (or 'any')
            for fr in self.forwards:
                frm = fr.get("from", "any")
                if frm != "any" and frm != port_name:
                    continue
                tos = fr.get("to", [])
                for t in tos:
                    # respect a small ttl/dedupe window if present
                    dedupe_window = float(fr.get("dedupe_window", 1.0))
                    key = f"{fkey_prefix}:{str(t)}"
                    last = self._recent_forwarded.get(key)
                    if last and (now - last) < dedupe_window:
                        if self.verbose:
                            try:
                                print(f"[router] dedupe suppressed forward from {port_name} to {t} (key={key})")
                            except Exception:
                                pass
                        continue
                    # perform forwarding actions
                    try:
                        ttype = t.get("type")
                        if ttype == "udp":
                            if self._udp_sock:
                                host = t.get("host")
                                port = int(t.get("port"))
                                try:
                                    self._udp_sock.sendto(data, (host, port))
                                except Exception:
                                    pass
                        elif ttype == "to_port":
                            # send into a named port's out_q so transports will emit it
                            target_port = t.get("port_name")
                            # optional explicit dest address for the out send
                            dest_host = t.get("host")
                            dest_port = t.get("port")
                            dest_addr = (dest_host, int(dest_port)) if dest_host and dest_port else None
                            if target_port in self.ports:
                                try:
                                    # put into that port's out_q so it will be sent out
                                    self.ports[target_port]["out_q"].put((dest_addr, data))
                                except Exception:
                                    pass
                        # mark forwarded
                        self._recent_forwarded[key] = now
                        if self.verbose:
                            try:
                                print(f"[router] forwarded packet from {port_name} to {t}")
                            except Exception:
                                pass
                    except Exception:
                        # best effort only
                        continue

        # choose destinations
        dest_ports = []
        if sysid is None:
            # unknown: broadcast to all except origin
            dest_ports = [p for p in self.ports.keys() if p != port_name]
        else:
            if sysid < 250:
                # vehicle -> only forward to ports that have observed GCS sysids 250-255
                for p, seen in self.observed_sysids.items():
                    if p == port_name:
                        continue
                    if any(250 <= s <= 255 for s in seen):
                        dest_ports.append(p)
            else:
                # sysid >= 250 (GCS) -> broadcast to all except origin
                dest_ports = [p for p in self.ports.keys() if p != port_name]

        # publish to out queues with addr resolution
        for dp in dest_ports:
            out_q: Queue = self.ports[dp]["out_q"]
            # resolve destination address for UDP transports
            dest_addr = self.last_addr.get(dp)
            # If dest_addr is unknown, router will still put None and transport may drop or handle
            try:
                out_q.put((dest_addr, data))
            except Exception:
                pass

    def run(self, router_in_q: Queue):
        print("[router] starting main loop")
        try:
            while True:
                self.route_once(router_in_q, timeout=0.5)
        except KeyboardInterrupt:
            print("[router] stopping")


__all__ = ["parse_sysid_compid", "Router"]
