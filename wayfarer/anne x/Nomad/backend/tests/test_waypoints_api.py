import os
import json
from pathlib import Path
from fastapi.testclient import TestClient
import backend.config_api as config_api

client = TestClient(config_api.app)


def test_demo_and_list_and_get_and_upload_and_send(tmp_path, monkeypatch):
    # monkeypatch mqtt publish to capture calls
    published = []

    def fake_publish(topic, payload, qos=0, retain=False, timeout_s=2.0):
        published.append((topic, payload))
        return True

    monkeypatch.setattr(config_api, '_mqtt_publish', fake_publish)

    # ensure Files/waypoints exists and is empty for test isolation
    repo_root = Path(config_api.REPO_ROOT)
    way_dir = repo_root / 'Files' / 'waypoints'
    way_dir.mkdir(parents=True, exist_ok=True)

    # call demo creation
    r = client.post('/api/waypoints/demo')
    assert r.status_code == 200
    j = r.json()
    assert j['ok'] is True
    files = j['files']
    assert len(files) == 6

    # list waypoints
    r = client.get('/api/waypoints')
    assert r.status_code == 200
    j = r.json()
    assert j['ok'] is True
    assert any(f['filename'] == files[0] for f in j['files'])

    # get a specific file
    fn = files[0]
    r = client.get(f'/api/waypoints/{fn}')
    assert r.status_code == 200
    j = r.json()
    assert j['ok'] is True
    assert 'waypoints' in j and len(j['waypoints']) > 0

    # upload raw YAML
    raw = """
    waypoints:
      - lat: 37.4125
        lon: -121.9980
        alt: 55
    """
    payload = {'filename': 'test_upload.yaml', 'raw': raw}
    r = client.post('/api/waypoints/upload_raw', json=payload)
    assert r.status_code == 200
    j = r.json()
    assert j['ok'] is True
    assert j['valid'] is True

    # send to drone (should invoke fake_publish)
    r = client.post('/api/waypoints/send', json={'sysid': 1, 'compid': 1, 'filename': 'test_upload.yaml'})
    assert r.status_code == 200
    j = r.json()
    assert j['ok'] is True
    assert published, 'expected mqtt publish to be called'
    # cleanup created files
    for p in way_dir.glob('*.yaml'):
        try:
            p.unlink()
        except Exception:
            pass


def test_download_mission_from_drone(tmp_path, monkeypatch):
    # monkeypatch mqtt publish to capture calls
    published = []

    def fake_publish(topic, payload, qos=0, retain=False, timeout_s=2.0):
        published.append((topic, payload))
        return True

    monkeypatch.setattr(config_api, '_mqtt_publish', fake_publish)

    # download mission from drone
    r = client.post('/api/waypoints/download', json={'sysid': 1, 'compid': 1})
    assert r.status_code == 200
    j = r.json()
    assert j['ok'] is True
    assert j['topic'] == 'command/1/1/download_mission'
    assert published, 'expected mqtt publish to be called'
    topic, payload = published[0]
    assert topic == 'command/1/1/download_mission'
    payload_obj = json.loads(payload)
    assert payload_obj['sysid'] == 1
    assert payload_obj['compid'] == 1
