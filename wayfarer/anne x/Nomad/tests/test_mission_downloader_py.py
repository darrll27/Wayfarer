import time

from backend.mav_router.mission_downloader import MissionDownloader


class FakeMsg:
    def __init__(self, mtype, **kwargs):
        self.type = mtype
        for k, v in kwargs.items():
            setattr(self, k, v)

    def get_type(self):
        return self.type


class FakeMav:
    def __init__(self, conn):
        self.conn = conn

    def mission_request_list_send(self, target_sys, target_comp):
        # vehicle responds with MISSION_COUNT
        # push a MISSION_COUNT into incoming
        # Using conn._incoming for test simplicity
        self.conn._incoming.append(FakeMsg("MISSION_COUNT", count=self.conn._mission_count))

    def mission_request_send(self, target_sys, target_comp, seq):
        # vehicle responds with the mission item for seq
        itm = self.conn._mission_data.get(seq)
        if itm is not None:
            self.conn._incoming.append(FakeMsg("MISSION_ITEM_INT", seq=seq, frame=itm.get("frame", 0), command=itm.get("command", 16), current=0, autocontinue=1, param1=itm.get("param1", 0.0), param2=itm.get("param2", 0.0), param3=itm.get("param3", 0.0), param4=itm.get("param4", 0.0), x=itm.get("x", 0), y=itm.get("y", 0), z=itm.get("z", 0.0)))


class FakeConn:
    def __init__(self, mission_list):
        # mission_list: list of dicts
        self._incoming = []
        self._mission_count = len(mission_list)
        self._mission_data = {it["seq"]: it for it in mission_list}
        self.mav = FakeMav(self)

    def recv_match(self, type=None, timeout=None):
        if not self._incoming:
            time.sleep(0.01)
            return None
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


def test_mission_downloader_basic():
    mission = [
        {"seq": 0, "frame": 0, "command": 16, "x": 11111111, "y": 22222222, "z": 10.0},
        {"seq": 1, "frame": 0, "command": 16, "x": 33333333, "y": 44444444, "z": 20.0},
    ]
    conn = FakeConn(mission)
    dl = MissionDownloader(conn)
    result = dl.download_mission(target_sys=1, target_comp=1, timeout=5)
    assert len(result) == 2
    assert result[0]["seq"] == 0 and result[1]["seq"] == 1
