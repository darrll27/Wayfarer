import os
import yaml
from typing import Dict, Any, List, Optional
from pydantic import BaseModel, Field


class ExternalGCSConfig(BaseModel):
    enable_send: bool = True
    enable_recv: bool = True


class DroneConfig(BaseModel):
    sysid: int
    nickname: Optional[str] = None
    # transport is a string key referencing top-level transports or a direct uri
    transport: str


class GroupConfig(BaseModel):
    name: str
    launch_delay_seconds: int = 5
    drones: List[DroneConfig] = Field(default_factory=list)


class TransportConfig(BaseModel):
    uri: str
    udp_target: Optional[str] = None


class NOMADConfig(BaseModel):
    server: Dict[str, Any] = Field(default_factory=lambda: {"host": "0.0.0.0", "port": 8000})
    internal_gcs_sysid: int = 250
    external_gcs: Dict[str, ExternalGCSConfig] = Field(default_factory=dict)
    groups: Dict[str, GroupConfig] = Field(default_factory=dict)
    # router and transports are required in the canonical schema
    router: Dict[str, Any] = Field(default_factory=dict)
    transports: Dict[str, TransportConfig] = Field(default_factory=dict)


DEFAULT_CONFIG_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "config", "config.yaml")


def load_config(path: str = None) -> NOMADConfig:
    if path is None:
        path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "config", "config.yaml"))
    if not os.path.exists(path):
        raise FileNotFoundError(f"Config not found: {path}")
    with open(path, "r") as fh:
        data = yaml.safe_load(fh) or {}

    # Strict canonical loading: do not accept legacy shapes such as top-level
    # `serial_bridges` or `groups[].drones` as a dict. This enforces a single
    # canonical schema and surfaces errors early for migration.
    # pydantic will validate types and raise informative errors on mismatch.
    # If the config file contains legacy keys, raise a ValueError instructing
    # the operator to migrate the config.

    # Reject known-legacy keys explicitly
    legacy_keys = ["serial_bridges"]
    for lk in legacy_keys:
        if lk in data:
            raise ValueError(f"Legacy config key '{lk}' is not supported. Please migrate to canonical 'transports' and remove '{lk}'.")

    # Validate group drone shapes: ensure each group's drones is a list
    raw_groups = data.get("groups") or {}
    for gname, gval in raw_groups.items():
        if isinstance(gval, dict):
            drones_raw = gval.get("drones", None)
            if drones_raw is None:
                continue
            if not isinstance(drones_raw, list):
                raise ValueError(f"Group '{gname}' drones must be a list of drone objects in canonical config. Found type: {type(drones_raw).__name__}")

    # Build the canonical pydantic model
    config = NOMADConfig(**data)
    return config


def save_config(config_obj: NOMADConfig, path: str = None) -> None:
    if path is None:
        path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "config", "config.yaml"))
    with open(path, "w") as fh:
        # Use dict but ensure serializable
        fh.write(yaml.safe_dump(config_obj.dict(), sort_keys=False))


def list_group_names(config: NOMADConfig) -> List[str]:
    return list(config.groups.keys())


def get_group_sysids(config: NOMADConfig, group_name: str) -> List[int]:
    grp = config.groups.get(group_name)
    if not grp:
        return []
    # canonical: grp.drones is a list of DroneConfig
    out: List[int] = []
    for d in grp.drones:
        try:
            out.append(int(d.sysid))
        except Exception:
            continue
    return out


def load_group_waypoints(group_name: str, base_dir: str = None) -> Dict[str, Any]:
    if base_dir is None:
        base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "groups", group_name))
    wp_path = os.path.join(base_dir, "waypoints.yaml")
    if not os.path.exists(wp_path):
        return {}
    with open(wp_path, "r") as fh:
        return yaml.safe_load(fh) or {}


def generate_per_drone_waypoints_for_group(config: NOMADConfig, group_name: str) -> Dict[int, Dict[str, Any]]:
    """Read group waypoints and generate per-drone copies with altitude decremented per stacked order.

    If drones mapping is [1,2,3] then drone 1 is top (no decrement), drone 2 alt -1, drone 3 alt -2, etc.
    Returns mapping sysid -> waypoint dict
    """
    wps = load_group_waypoints(group_name)
    drone_ids = get_group_sysids(config, group_name)
    drone_ids_sorted = sorted(drone_ids, key=lambda x: drone_ids.index(x) if x in drone_ids else 0)

    out: Dict[int, Dict[str, Any]] = {}
    if not wps or "waypoints" not in wps:
        return out

    for idx, sysid in enumerate(drone_ids_sorted):
        # top drone idx=0 => decrement 0, idx=1 => decrement 1
        dec = idx
        copied = {"waypoints": []}
        for wp in wps.get("waypoints", []):
            wp_copy = dict(wp)
            if isinstance(wp_copy.get("alt"), (int, float)):
                wp_copy["alt"] = wp_copy["alt"] - dec
            copied["waypoints"].append(wp_copy)
        out[sysid] = copied

    return out
