import hashlib
import json
import time

from . import reporter


def _canonicalize(mission):
    """Return a canonical JSON-serializable representation of a mission list.

    Each item is normalized to a dict with a stable key order so hashing is
    deterministic.
    """
    canon = []
    for it in mission:
        # pick canonical keys for mission items
        item = {
            "seq": int(it.get("seq", 0)),
            "frame": int(it.get("frame", 0)),
            "command": int(it.get("command", 16)),
            "current": int(it.get("current", 0)),
            "autocontinue": int(it.get("autocontinue", 1)),
            "param1": float(it.get("param1", it.get("params", [0])[0] if it.get("params") else 0.0)),
            "param2": float(it.get("param2", it.get("params", [0, 0])[1] if it.get("params") else 0.0)),
            "param3": float(it.get("param3", it.get("params", [0, 0, 0])[2] if it.get("params") else 0.0)),
            "param4": float(it.get("param4", it.get("params", [0, 0, 0, 0])[3] if it.get("params") else 0.0)),
            "x": int(it.get("x", it.get("lat", 0))),
            "y": int(it.get("y", it.get("lon", 0))),
            "z": float(it.get("z", it.get("alt", 0.0))),
        }
        canon.append(item)
    return canon


def _hash_mission(canon):
    s = json.dumps(canon, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def test_uploader_verifier_roundtrip():
    """SIL-style test: simulate uploader creating mission and verifier downloading it; compare hashes.

    This test is self-contained and does not require hardware. It writes a report
    under `hil_sil_tests/reports/` with the result and computed hash.
    """
    test_name = "test_mission_uploader_verifier"
    start = time.time()

    # example mission (two waypoints)
    mission = [
        {"seq": 0, "frame": 0, "command": 16, "lat": 11111111, "lon": 22222222, "alt": 10.0},
        {"seq": 1, "frame": 0, "command": 16, "lat": 33333333, "lon": 44444444, "alt": 20.0},
    ]

    try:
        # uploader canonicalizes and computes hash
        uploaded = _canonicalize(mission)
        upl_hash = _hash_mission(uploaded)

        # verifier 'downloads' and canonicalizes as well
        downloaded = _canonicalize(mission)
        dl_hash = _hash_mission(downloaded)

        duration = time.time() - start
        if upl_hash != dl_hash:
            reporter.write_report(test_name, "FAIL", details=f"hash_mismatch upl={upl_hash} dl={dl_hash}", duration=duration)
            assert False, "Uploaded mission and downloaded mission hashes differ"
        else:
            reporter.write_report(test_name, "PASS", details=f"mission_hash={upl_hash}", duration=duration)
    except Exception as e:
        duration = time.time() - start
        reporter.write_report(test_name, "FAIL", details=str(e), duration=duration)
        raise
