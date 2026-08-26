"""Tests for adding a serving size to an existing custom food.

A food created through add_custom_food has exactly one measure. Logging it by
the piece as well as by weight needs a second one, so update_custom_food takes
a measure with no id as "add this".
"""

from __future__ import annotations

from pathlib import Path

import pytest

from cronometer_mcp.client import CronometerClient, CronometerError


def _client(tmp_path: Path, food: dict) -> tuple[CronometerClient, list[dict]]:
    """Client whose get_food returns `food` and whose save records the payload."""
    client = CronometerClient(session_path=tmp_path / "session.json")
    client._user_id = 123
    client._token = "TOKEN"
    saved: list[dict] = []

    def fake_get_food(food_id):
        return food

    def fake_save(f, *, keep_measures=True):
        saved.append(f)
        return f

    client.get_food = fake_get_food  # type: ignore[method-assign]
    client._save_food = fake_save  # type: ignore[method-assign]
    return client, saved


def _food() -> dict:
    return {
        "id": 1,
        "owner": 123,
        "name": "Test food",
        "measures": [{"id": 55, "name": "g", "value": 1.0, "amount": 1.0, "type": "Atomic"}],
        "nutrients": [{"id": 208, "amount": 100.0}],
    }


def test_measure_without_id_is_added(tmp_path):
    """A per-piece measure joins the existing gram measure rather than replacing it."""
    client, saved = _client(tmp_path, _food())

    client.update_custom_food(1, measures=[{"name": "karkki", "grams": 4.5}])

    measures = saved[0]["measures"]
    assert [m["name"] for m in measures] == ["g", "karkki"]
    added = measures[1]
    assert added["value"] == 4.5
    # id 0 tells Cronometer to assign a real one.
    assert added["id"] == 0
    assert added["type"] == "Atomic"


def test_added_measure_inherits_the_food_s_measure_type(tmp_path):
    """A weight-based recipe keeps Weight measures, not Atomic ones."""
    food = _food()
    food["measures"][0]["type"] = "Weight"
    client, saved = _client(tmp_path, food)

    client.update_custom_food(1, measures=[{"name": "kupillinen", "grams": 137}])

    assert saved[0]["measures"][1]["type"] == "Weight"


def test_existing_measure_is_still_patched_by_id(tmp_path):
    """Passing an id keeps the old behaviour: rename or reweigh in place."""
    client, saved = _client(tmp_path, _food())

    client.update_custom_food(1, measures=[{"measure_id": 55, "name": "gramma"}])

    assert len(saved[0]["measures"]) == 1
    assert saved[0]["measures"][0]["name"] == "gramma"


def test_unknown_id_still_errors(tmp_path):
    """A wrong id is a mistake, not a request to add a measure."""
    client, _ = _client(tmp_path, _food())

    with pytest.raises(CronometerError, match="no measure 999"):
        client.update_custom_food(1, measures=[{"measure_id": 999, "grams": 2}])


def test_new_measure_needs_name_and_grams(tmp_path):
    client, _ = _client(tmp_path, _food())

    with pytest.raises(CronometerError, match="needs both name and grams"):
        client.update_custom_food(1, measures=[{"name": "karkki"}])


def test_duplicate_name_is_refused(tmp_path):
    """Two measures with the same name would be indistinguishable when logging."""
    client, _ = _client(tmp_path, _food())

    with pytest.raises(CronometerError, match="already has a measure named"):
        client.update_custom_food(1, measures=[{"name": "g", "grams": 5}])
