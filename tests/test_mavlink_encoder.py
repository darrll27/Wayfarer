import pytest

from backend.mav_router import mavlink_encoder


def test_is_mavlink2_detector():
    assert mavlink_encoder.is_mavlink2_packet(b"\xfd\x00\x00")
    assert not mavlink_encoder.is_mavlink2_packet(b"\xfe\x00\x00")


def test_encode_command_long_basic():
    # encode a simple COMMAND_LONG and ensure bytes are returned
    b = mavlink_encoder.encode_command_long(1, 1, 176, params=[0, 0, 0, 0, 0, 0, 0])
    assert isinstance(b, (bytes, bytearray))
    assert len(b) > 8


def test_encode_mission_item_int_basic():
    b = mavlink_encoder.encode_mission_item_int(1, 1, seq=0, frame=0, command=16, params=[0, 0, 0, 0], x=0, y=0, z=10.0)
    assert isinstance(b, (bytes, bytearray))
    assert len(b) > 8
 