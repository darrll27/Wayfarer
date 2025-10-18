TOPIC_VERSION = "wayfarer/v1"
DEFAULT_HEARTBEAT_SECS = 2.0
DISCOVERY_TOPIC = "{root}/devices/{device_id}/telem/state/discovery"
HEARTBEAT_TOPIC = "{root}/devices/{device_id}/telem/state/heartbeat"
RAW_MAVLINK_TOPIC = "{root}/devices/{device_id}/telem/raw/mavlink/{msg}"
NORM_ATTITUDE_TOPIC = "{root}/devices/{device_id}/telem/pose/attitude"
CMD_WILDCARD = "{root}/devices/+/cmd/#"
