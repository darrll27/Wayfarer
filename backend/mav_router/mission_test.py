from __future__ import annotations

import json
import time
import hashlib
from typing import List, Dict, Any

from pymavlink import mavutil

from .mission_uploader import MissionUploader, MissionUploadError
from .mission_downloader import MissionDownloader, MissionDownloadError


def _canonicalize(mission: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    # minimal canonicalization similar to hil_sil_tests: keep stable ordering and remove frame
    canon = []
    for it in mission:
        entry = dict(it)
        entry.pop("frame", None)
        # ensure numeric types are normalized
        for k in ["seq", "command", "x", "y"]:
            if k in entry:
                try:
                    entry[k] = int(entry[k])
                except Exception:
                    pass
        for k in ["z", "param1", "param2", "param3", "param4"]:
            if k in entry:
                try:
                    entry[k] = float(entry[k])
                except Exception:
                    pass
        canon.append(entry)
    return canon


def _hash_mission(canon: List[Dict[str, Any]]) -> str:
    s = json.dumps(canon, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def run_mission_test(conn_string: str, mission: List[Dict[str, Any]], timeout: float = 30.0) -> Dict[str, Any]:
    """Run a mission upload/download verification against a connection string.

    conn_string: a pymavlink connection string, e.g. 'udpout:127.0.0.1:14550' or '/dev/ttyUSB0:57600'
    mission: list of mission dicts (seq, frame, command, x|lat, y|lon, z|alt, params)
    Returns a dict with keys: status ('PASS'|'FAIL'), details, upl_hash, dl_hash
    """
    result = {"status": "FAIL", "details": "", "upl_hash": None, "dl_hash": None}

    # open pymavlink connection
    try:
        conn = mavutil.mavlink_connection(conn_string)
    except Exception as e:
        result["details"] = f"failed to open connection: {e}"
        return result

    # wait for heartbeat
    hb = conn.wait_heartbeat(timeout=5)
    if hb is None:
        result["details"] = "no heartbeat seen on connection"
        try:
            conn.close()
        except Exception:
            pass
        return result

    try:
        uploader = MissionUploader(conn)
        uploader.upload_mission(mission, target_sys=hb.get_srcSystem(), target_comp=hb.get_srcComponent(), timeout=timeout)
    except MissionUploadError as e:
        result["details"] = f"upload failed: {e}"
        try:
            conn.close()
        except Exception:
            pass
        return result

    try:
        downloader = MissionDownloader(conn)
        downloaded = downloader.download_mission(target_sys=hb.get_srcSystem(), target_comp=hb.get_srcComponent(), timeout=timeout)
    except MissionDownloadError as e:
        result["details"] = f"download failed: {e}"
        try:
            conn.close()
        except Exception:
            pass
        return result

    try:
        upl_canon = _canonicalize(mission)
        dl_canon = _canonicalize(downloaded)
        upl_hash = _hash_mission(upl_canon)
        dl_hash = _hash_mission(dl_canon)
        result["upl_hash"] = upl_hash
        result["dl_hash"] = dl_hash
        if upl_hash == dl_hash:
            result["status"] = "PASS"
            result["details"] = "hash_match"
        else:
            result["status"] = "FAIL"
            result["details"] = f"hash_mismatch upl={upl_hash} dl={dl_hash}"
    except Exception as e:
        result["details"] = f"comparison failed: {e}"
    finally:
        try:
            conn.close()
        except Exception:
            pass

    return result


__all__ = ["run_mission_test"]
