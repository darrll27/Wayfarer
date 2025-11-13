"""API-level MAVLink decoder.

This module attempts to use `pymavlink` to parse raw MAVLink bytes into messages.
If `pymavlink` is not available it returns a safe fallback (hex and length) so the
API remains functional without a hard dependency.
"""
from typing import List, Any

try:
    from pymavlink import mavutil
    _HAS_PY = True
except Exception:
    mavutil = None  # type: ignore
    _HAS_PY = False


class MAVDecoder:
    def __init__(self):
        self.available = _HAS_PY
        if self.available:
            # MAVLink parser instance (no output file; we use parse_char)
            self.parser = mavutil.mavlink.MAVLink(None)
        else:
            self.parser = None

    def parse_bytes(self, data: bytes) -> List[Any]:
        """Parse raw bytes and return a list of parsed messages or fallback info.

        Returns a list of dicts describing each parsed message. If pymavlink is
        not installed, returns a single dict with raw hex and length.
        """
        if not self.available:
            return [{"raw_hex": data.hex(), "len": len(data)}]

        msgs = []
        # Feed byte-by-byte into parser
        for b in data:
            try:
                # parse_char expects integer/bytes-like; returns message or None
                m = self.parser.parse_char(bytes([b]))  # type: ignore[arg-type]
            except Exception:
                m = None
            if m is not None:
                try:
                    # many pymavlink message objects provide .to_dict()
                    if hasattr(m, "to_dict"):
                        msgs.append(m.to_dict())
                    else:
                        msgs.append(str(m))
                except Exception:
                    msgs.append(str(m))

        return msgs


decoder = MAVDecoder()
