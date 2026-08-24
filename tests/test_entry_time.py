"""Tests for logging a diary entry at an explicit time.

A meal is usually logged after it was eaten, so add_food_entry takes the real
time of day. Without it the entry lands at "now" and an auto meal group picks
the wrong slot, which then needs a second edit_food_entry call to repair.
"""

from __future__ import annotations

import datetime as _dt
from pathlib import Path

import pytest

from cronometer_mcp.client import CronometerClient
from cronometer_mcp.server import _parse_time


class FakeResp:
    def __init__(self, body, status: int = 200) -> None:
        self._body = body
        self.status_code = status

    def raise_for_status(self) -> None:  # pragma: no cover - trivial
        pass

    def json(self):
        return self._body


def _client(tmp_path: Path) -> CronometerClient:
    client = CronometerClient(session_path=tmp_path / "session.json")
    client._user_id = 123
    client._token = "TOKEN"
    client._timezone = "Europe/Helsinki"
    return client


def _capture_serving(client: CronometerClient) -> dict:
    captured: dict = {}

    def fake_post(endpoint, json=None):
        captured["payload"] = json
        return FakeResp({"result": "SUCCESS", "id": 999})

    client._http.post = fake_post  # type: ignore[method-assign]
    return captured


def test_explicit_time_is_stamped(tmp_path):
    """The entry carries the time it was eaten, not the time it was logged."""
    client = _client(tmp_path)
    captured = _capture_serving(client)

    client.add_serving(
        food_id=1, measure_id=0, grams=150.0, time=_dt.time(10, 15)
    )

    assert captured["payload"]["serving"]["time"] == "10:15:0"


def test_auto_group_follows_the_given_time(tmp_path):
    """08:00 is Breakfast even when the call happens at lunchtime."""
    client = _client(tmp_path)
    captured = _capture_serving(client)

    client.add_serving(food_id=1, measure_id=0, grams=150.0, time=_dt.time(8, 0))

    assert captured["payload"]["serving"]["order"] == (1 << 16) | 1


def test_explicit_group_wins_over_the_given_time(tmp_path):
    """An explicit meal slot is never overridden by the hour heuristic."""
    client = _client(tmp_path)
    captured = _capture_serving(client)

    client.add_serving(
        food_id=1,
        measure_id=0,
        grams=150.0,
        diary_group=4,
        time=_dt.time(8, 0),
    )

    assert captured["payload"]["serving"]["order"] == (4 << 16) | 1


def test_time_defaults_to_now(tmp_path):
    """Omitting the time keeps the old behaviour: stamp the current moment."""
    client = _client(tmp_path)
    captured = _capture_serving(client)

    before = client.now()
    client.add_serving(food_id=1, measure_id=0, grams=150.0)
    after = client.now()

    stamped = captured["payload"]["serving"]["time"]
    hours = {before.hour, after.hour}
    assert int(stamped.split(":")[0]) in hours


@pytest.mark.parametrize(
    ("given", "expected"),
    [("10:15", _dt.time(10, 15)), ("10:15:30", _dt.time(10, 15, 30))],
)
def test_parse_time_accepts_both_forms(given, expected):
    assert _parse_time(given) == expected


def test_parse_time_rejects_nonsense():
    with pytest.raises(ValueError):
        _parse_time("aamulla")
