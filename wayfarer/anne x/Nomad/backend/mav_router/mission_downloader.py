"""Mission downloader state machine (GCS pulls mission from Vehicle).

This module provides MissionDownloader which requests a mission (MISSION_REQUEST_LIST),
receives MISSION_COUNT, then requests each item with MISSION_REQUEST and collects
MISSION_ITEM_INT messages into a list which it returns.
"""
from __future__ import annotations

import time
from typing import List, Dict, Any


class MissionDownloadError(RuntimeError):
    pass


class MissionDownloader:
    def __init__(self, conn):
        self.conn = conn

    def download_mission(self, target_sys: int = 1, target_comp: int = 1, timeout: float = 30.0) -> List[Dict[str, Any]]:
        # request mission list
        try:
            self.conn.mav.mission_request_list_send(target_sys, target_comp)
        except Exception as e:
            raise MissionDownloadError(f"failed to send MISSION_REQUEST_LIST: {e}")

        start = time.time()
        count = None
        items = {}

        while True:
            if time.time() - start > timeout:
                raise MissionDownloadError("timeout waiting for mission count/items")

            # accept both regular and INT variants of count/item messages
            msg = self.conn.recv_match(type=["MISSION_COUNT", "MISSION_COUNT_INT", "MISSION_ITEM_INT", "MISSION_ITEM"], timeout=1)
            if msg is None:
                continue

            mtype = getattr(msg, "get_type", lambda: getattr(msg, "type", None))()
            if isinstance(mtype, str) and mtype.upper() in ("MISSION_COUNT", "MISSION_COUNT_INT"):
                count = int(getattr(msg, "count", 0))
                if count == 0:
                    return []
                # request first item; prefer INT request
                try:
                    try:
                        self.conn.mav.mission_request_int_send(target_sys, target_comp, 0)
                    except Exception:
                        # fallback to non-INT request
                        self.conn.mav.mission_request_send(target_sys, target_comp, 0)
                except Exception as e:
                    raise MissionDownloadError(f"failed to request first mission item: {e}")

            elif isinstance(mtype, str) and mtype.upper() in ("MISSION_ITEM_INT", "MISSION_ITEM"):
                seq = int(getattr(msg, "seq", 0))
                items[seq] = msg
                # if we have all items, return reconstructed list
                if count is not None and len(items) >= count:
                    # build ordered mission list
                    ordered = []
                    for i in range(count):
                        m = items.get(i)
                        if m is None:
                            raise MissionDownloadError(f"missing mission item seq {i}")
                        ordered.append({
                            "seq": int(m.seq),
                            "frame": int(getattr(m, "frame", 0)),
                            "command": int(getattr(m, "command", 0)),
                            "current": int(getattr(m, "current", 0)),
                            "autocontinue": int(getattr(m, "autocontinue", 0)),
                            "param1": float(getattr(m, "param1", 0.0)),
                            "param2": float(getattr(m, "param2", 0.0)),
                            "param3": float(getattr(m, "param3", 0.0)),
                            "param4": float(getattr(m, "param4", 0.0)),
                            "x": int(getattr(m, "x", 0)),
                            "y": int(getattr(m, "y", 0)),
                            "z": float(getattr(m, "z", 0.0)),
                        })
                    return ordered
                else:
                    # request next item; prefer INT variant
                    next_seq = seq + 1
                    try:
                        try:
                            self.conn.mav.mission_request_int_send(target_sys, target_comp, next_seq)
                        except Exception:
                            self.conn.mav.mission_request_send(target_sys, target_comp, next_seq)
                    except Exception:
                        pass
            else:
                # ignore other messages
                continue


__all__ = ["MissionDownloader", "MissionDownloadError"]
