"""Mission uploader state machine (GCS -> Vehicle).

This module provides a tiny MissionUploader class that performs the
MISSION_COUNT -> MISSION_REQUEST -> MISSION_ITEM_INT -> MISSION_ACK
exchange using a pymavlink connection-like object.

The uploader is written to be testable: it uses `conn.mav.<msg>_send(...)`
to send and `conn.recv_match(type=..., timeout=...)` to receive vehicle
requests/acks. It returns True on success, raises RuntimeError on failure.
"""
from __future__ import annotations

import time
from typing import List, Dict, Any


class MissionUploadError(RuntimeError):
    pass


class MissionUploader:
    def __init__(self, conn):
        """conn must expose `mav` for send_* methods and `recv_match` for incoming messages."""
        self.conn = conn

    def upload_mission(self, mission: List[Dict[str, Any]], target_sys: int = 1, target_comp: int = 1, timeout: float = 30.0) -> bool:
        """Upload a mission list to the connected vehicle.

        mission: list of dicts with keys: seq, frame, command, x, y, z, params (optional)
        Returns True on success; raises MissionUploadError on failure.
        """
        count = len(mission)
        # send MISSION_COUNT to vehicle
        try:
            print(f"[MissionUploader] sending MISSION_COUNT={count} to {target_sys}/{target_comp}")
            self.conn.mav.mission_count_send(target_sys, target_comp, count)
        except Exception as e:
            raise MissionUploadError(f"failed to send MISSION_COUNT: {e}")

        start = time.time()
        sent = {}

        while True:
            if time.time() - start > timeout:
                raise MissionUploadError("timeout waiting for mission requests/ack")

            # wait for either a MISSION_REQUEST / MISSION_REQUEST_INT (vehicle asking for seq) or MISSION_ACK
            msg = self.conn.recv_match(type=["MISSION_REQUEST", "MISSION_REQUEST_INT", "MISSION_ACK"], timeout=1)
            if msg is None:
                continue

            mtype = getattr(msg, "get_type", lambda: getattr(msg, "type", None))()
            # some fake messages in tests may not implement get_type(); fall back
            if isinstance(mtype, str) and mtype.upper() in ("MISSION_REQUEST", "MISSION_REQUEST_INT"):
                # both MISSION_REQUEST and MISSION_REQUEST_INT include 'seq'
                seq = int(getattr(msg, "seq", getattr(msg, "param1", 0)))
                print(f"[MissionUploader] received MISSION_REQUEST for seq={seq}")
                if seq < 0 or seq >= count:
                    raise MissionUploadError(f"vehicle requested invalid seq {seq}")

                itm = mission[seq]
                # send MISSION_ITEM_INT with fields: target_system, target_component, seq, frame, command, current, autocontinue, param1..4, x, y, z
                params = itm.get("params") or [itm.get("param1", 0.0), itm.get("param2", 0.0), itm.get("param3", 0.0), itm.get("param4", 0.0)]
                p1, p2, p3, p4 = (float(params[i]) if i < len(params) else 0.0 for i in range(4))
                x = int(itm.get("x", itm.get("lat", 0)))
                y = int(itm.get("y", itm.get("lon", 0)))
                z = float(itm.get("z", itm.get("alt", 0.0)))
                try:
                    self.conn.mav.mission_item_int_send(
                        target_sys,
                        target_comp,
                        int(seq),
                        int(itm.get("frame", 0)),
                        int(itm.get("command", 16)),
                        int(itm.get("current", 0)),
                        int(itm.get("autocontinue", 1)),
                        float(p1),
                        float(p2),
                        float(p3),
                        float(p4),
                        int(x),
                        int(y),
                        float(z),
                    )
                    sent[seq] = True
                    print(f"[MissionUploader] sent MISSION_ITEM_INT seq={seq} to {target_sys}/{target_comp}")
                except Exception as e:
                    raise MissionUploadError(f"failed to send MISSION_ITEM_INT seq={seq}: {e}")
            else:
                # MISSION_ACK
                if isinstance(mtype, str) and mtype.upper() == "MISSION_ACK":
                    # success
                    print(f"[MissionUploader] received MISSION_ACK from {getattr(msg, 'srcSystem', target_sys)}/{getattr(msg, 'srcComponent', target_comp)}")
                    return True
                # unknown message type: ignore


__all__ = ["MissionUploader", "MissionUploadError"]
