from scripts.build_live_projections import _pitcher_ids_from_roster


def _roster(entries):
    return {"roster": entries}


def test_pitcher_ids_from_roster_filters_by_position_code():
    payload = _roster([
        {"position": {"code": "1"}, "person": {"id": 111}},
        {"position": {"code": "2"}, "person": {"id": 222}},  # catcher, no cuenta
        {"position": {"code": "1"}, "person": {"id": 333}},
    ])
    assert _pitcher_ids_from_roster(payload, exclude_id=None) == [111, 333]


def test_pitcher_ids_from_roster_excludes_todays_starter():
    payload = _roster([
        {"position": {"code": "1"}, "person": {"id": 111}},
        {"position": {"code": "1"}, "person": {"id": 800048}},
    ])
    assert _pitcher_ids_from_roster(payload, exclude_id=800048) == [111]


def test_pitcher_ids_from_roster_none_payload_is_empty():
    assert _pitcher_ids_from_roster(None, exclude_id=None) == []


def test_pitcher_ids_from_roster_empty_roster_list():
    assert _pitcher_ids_from_roster({"roster": []}, exclude_id=None) == []
