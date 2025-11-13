import hashlib
import json


def canonicalize_mission(mission):
    canon = []
    for it in mission:
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


def hash_mission(canon):
    s = json.dumps(canon, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(s.encode("utf-8")).hexdigest()
