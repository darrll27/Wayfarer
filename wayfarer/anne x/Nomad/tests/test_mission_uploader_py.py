import time

from backend.mav_router.mission_uploader import MissionUploader, MissionUploadError


class FakeMsg:
    def __init__(self, mtype, **kwargs):
        self.type = mtype
        for k, v in kwargs.items():
            setattr(self, k, v)

    def get_type(self):
        return self.type


class FakeMav:
    def __init__(self):
        self.sent = []

    def mission_count_send(self, target_sys, target_comp, count):
        self.sent.append(("MISSION_COUNT", target_sys, target_comp, count))

    def mission_item_int_send(self, target_sys, target_comp, seq, frame, command, current, autocontinue, p1, p2, p3, p4, x, y, z):
        self.sent.append(("MISSION_ITEM_INT", seq, frame, command, current, autocontinue, p1, p2, p3, p4, x, y, z))


class FakeConn:
    def __init__(self, incoming_msgs):
        self.mav = FakeMav()
        # incoming_msgs is a list of FakeMsg to be returned in order
        self._incoming = list(incoming_msgs)

    def recv_match(self, type=None, timeout=None):
        # ignore timeout for simplicity; pop next message of matching type
        if not self._incoming:
            time.sleep(0.01)
            return None
        # if type is a list, check for one of them
        nxt = self._incoming.pop(0)
        if type is None:
            return nxt
        if isinstance(type, (list, tuple)):
            if nxt.type in type:
                return nxt
            else:
                return None
        else:
            if nxt.type == type:
                return nxt
            else:
                return None


def test_mission_uploader_basic():
    # prepare a mission with 2 items
    mission = [
        {"seq": 0, "frame": 0, "command": 16, "x": 11111111, "y": 22222222, "z": 10.0},
        {"seq": 1, "frame": 0, "command": 16, "x": 33333333, "y": 44444444, "z": 20.0},
    ]

    # simulate vehicle requesting seq 0, then seq 1, then sending MISSION_ACK
    incoming = [FakeMsg("MISSION_REQUEST", seq=0), FakeMsg("MISSION_REQUEST", seq=1), FakeMsg("MISSION_ACK")]
    conn = FakeConn(incoming)
    uploader = MissionUploader(conn)
    ok = uploader.upload_mission(mission, target_sys=1, target_comp=1, timeout=5)
    assert ok is True

    # verify that mission_count and two mission item sends were recorded
    sent = conn.mav.sent
    assert sent[0][0] == "MISSION_COUNT" and sent[0][3] == 2
    assert sent[1][0] == "MISSION_ITEM_INT" and sent[1][1] == 0
    assert sent[2][0] == "MISSION_ITEM_INT" and sent[2][1] == 1
