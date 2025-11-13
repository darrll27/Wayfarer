"""Shared runtime state for NOMAD services.

Keeps latest messages and simple helpers in one place so multiple processes/modules
can import/update without circular imports.
"""
from typing import Dict, Any

# latest_messages: sysid -> arbitrary dict
latest_messages: Dict[int, Dict[str, Any]] = {}

def set_latest(sysid: int, payload: Dict[str, Any]):
    latest_messages[sysid] = payload

def get_latest(sysid: int):
    return latest_messages.get(sysid)
