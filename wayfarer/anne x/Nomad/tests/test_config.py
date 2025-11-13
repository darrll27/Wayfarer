import os
import sys

# Make sure src is discoverable
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

from nomad.config import load_config, get_group_sysids


def test_load_config_exists():
    cfg = load_config()
    assert cfg is not None
    assert hasattr(cfg, "groups")
    assert "example_group" in cfg.groups


def test_get_group_sysids():
    cfg = load_config()
    ids = get_group_sysids(cfg, "example_group")
    assert isinstance(ids, list)
    # example config defines sysid 1
    assert 1 in ids
