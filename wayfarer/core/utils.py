import json
import numpy as np

def safe_json(obj):
    """Recursively convert non-JSON-safe types (bytearray, bytes, numpy, etc.)."""
    if isinstance(obj, (bytes, bytearray)):
        try:
            return obj.decode("utf-8", errors="ignore")
        except Exception:
            return list(obj)
    if isinstance(obj, dict):
        return {k: safe_json(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set)):
        return [safe_json(v) for v in obj]
    if isinstance(obj, (np.generic,)):
        return obj.item()
    return obj
