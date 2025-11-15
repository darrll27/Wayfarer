from backend.waypoint_validator.validator import validate_waypoints


def test_validate_good_waypoints():
    w = [
        {"lat": 37.4125, "lon": -121.9980, "alt": 55},
        {"lat": 37.4130, "lon": -121.9982, "alt": 60},
    ]
    ok, details, norm = validate_waypoints(w)
    assert ok is True
    assert isinstance(norm, list)
    assert len(norm) == 2


def test_validate_bad_waypoints():
    w = [{"lat": 'nope', "lon": -121.0}]
    ok, details, norm = validate_waypoints(w)
    assert ok is False
    assert 'must be numeric' in details or 'missing' in details
