# Topic schema / resolver for Pathfinder to consume Wayfarer bridge manifest.
#
# Responsibilities:
#  - Format topic patterns declared in the bridge manifest
#  - Choose the best command topic for a given action/sysid/device based on
#    a well-known priority list (device_cmd, command_long, global_cmd)
#
# Keep all topic-related formatting and selection logic here so other modules
# (helpers, mission_api) can import these helpers and not reimplement formatting.

DEFAULT_CMD_PRIORITY = ["cmd"]

def format_topic(manifest, key, **kwargs):
    """Format a topic pattern from manifest. Return None if key missing or format fails."""
    if not manifest or "topics" not in manifest:
        return None
    pattern = manifest["topics"].get(key)
    if not pattern:
        return None
    try:
        return pattern.format(**kwargs)
    except Exception:
        # best-effort simple replacement
        t = pattern
        for k, v in kwargs.items():
            t = t.replace("{" + k + "}", str(v))
        return t

def choose_command_topic(manifest, sysid, device_id=None, action=""):
    """
    Choose the first available command topic according to priority.
    Returns (topic, key) or (None, None) if none available.
    """
    if not manifest or "topics" not in manifest:
        return None, None
    topics = manifest.get("topics", {})
    for key in DEFAULT_CMD_PRIORITY:
        if key in topics:
            topic = format_topic(manifest, key, sysid=sysid, device_id=device_id or "", action=action)
            if topic:
                return topic, key
    return None, None
