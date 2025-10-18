from dataclasses import dataclass
from typing import Dict, Any, Optional

@dataclass
class Packet:
    device_id: str
    schema: str              # "mavlink", "nomad" (normalized), etc.
    msg_type: str
    fields: Dict[str, Any]
    timestamp: float
    origin: str              # transport/router name (for loop prevention)
