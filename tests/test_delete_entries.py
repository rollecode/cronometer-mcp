"""Tests for deleting diary entries of any type.

The v3 diary-entries endpoint takes any entry, but delete_entries only ever
matched servingId, so a biometric from a misbehaving scale could not be removed
through the MCP even though the Cronometer app removes it fine.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from cronometer_mcp.client import CronometerClient, CronometerError


class FakeResp:
    def __init__(self, status: int = 204) -> None:
        self.status_code = status
        self.text = ""


DIARY = [
    {"type": "Serving", "servingId": 1, "foodId": 10},
    {
        "type": "Biometric",
        "biometricId": 2,
        "metricId": 8,
        "amount": 75.0,
        # Apple Health entries carry nested sample data here.
        "meta": {"sampleDataV2": {"count": 1, "mean": 75.0}},
    },
    {"type": "Exercise", "exerciseId": 3, "minutes": 30},
    {"type": "Note", "noteId": 4, "text": "note"},
]


def _client(tmp_path: Path, *, actually_deletes: bool = True):
    """Client over a fake diary. With actually_deletes=False the endpoint
    answers 204 without removing anything, which is what Cronometer does when
    the payload lacks an id."""
    client = CronometerClient(session_path=tmp_path / "session.json")
    client._user_id = 123
    client._token = "TOKEN"
    sent: list[dict] = []
    diary = [dict(e) for e in DIARY]

    def fake_get_diary(day=None):
        return {"diary": [dict(e) for e in diary]}

    def fake_v3(method, path, json_body=None):
        sent.append({"method": method, "path": path, "body": json_body})
        if actually_deletes:
            gone = {b.get("id") for b in json_body["diaryEntries"]}
            diary[:] = [
                e for e in diary
                if not any(e.get(f) in gone for f in CronometerClient._ID_FIELD.values())
            ]
        return FakeResp()

    client.get_diary = fake_get_diary  # type: ignore[method-assign]
    client._request_v3 = fake_v3  # type: ignore[method-assign]
    return client, sent


def test_biometric_is_deleted_by_its_own_id(tmp_path):
    """A biometric has no servingId, so matching on that field found nothing."""
    client, sent = _client(tmp_path)

    result = client.delete_entries(["2"], entry_type="Biometric")

    assert result == {"removed": ["2"], "count": 1}
    body = sent[0]["body"]["diaryEntries"]
    assert len(body) == 1
    assert body[0]["biometricId"] == 2


def test_exercise_is_deleted_by_its_own_id(tmp_path):
    client, sent = _client(tmp_path)

    result = client.delete_entries(["3"], entry_type="Exercise")

    assert result == {"removed": ["3"], "count": 1}
    assert sent[0]["body"]["diaryEntries"][0]["exerciseId"] == 3


def test_serving_deletion_is_unchanged(tmp_path):
    """The original behaviour still works, ids reported from servingId."""
    client, sent = _client(tmp_path)

    result = client.delete_entries(["1"], entry_type="Serving")

    assert result == {"removed": ["1"], "count": 1}
    assert sent[0]["body"]["diaryEntries"][0]["servingId"] == 1


def test_type_narrows_the_match(tmp_path):
    """Id 2 is a biometric; asking for a Serving with that id must find nothing."""
    client, sent = _client(tmp_path)

    result = client.delete_entries(["2"], entry_type="Serving")

    assert result == {"removed": [], "count": 0}
    assert sent == []


def test_without_a_type_any_id_field_matches(tmp_path):
    """Callers that pass no type still get the old catch-all behaviour."""
    client, _ = _client(tmp_path)

    result = client.delete_entries(["3"])

    assert result == {"removed": ["3"], "count": 1}


def test_unknown_type_errors(tmp_path):
    client, _ = _client(tmp_path)

    with pytest.raises(CronometerError, match="Unknown diary entry type"):
        client.delete_entries(["1"], entry_type="Nonsense")


def test_meta_is_stripped_before_sending(tmp_path):
    """The endpoint answers 400 when meta is present, so it never goes out."""
    client, sent = _client(tmp_path)

    client.delete_entries(["2"], entry_type="Biometric")

    body = sent[0]["body"]["diaryEntries"][0]
    assert "meta" not in body
    # Everything that identifies the entry is still there.
    assert body["biometricId"] == 2
    assert body["type"] == "Biometric"


def test_id_field_is_sent(tmp_path):
    """Without a plain "id" the endpoint returns 204 and deletes nothing."""
    client, sent = _client(tmp_path)

    client.delete_entries(["2"], entry_type="Biometric")

    assert sent[0]["body"]["diaryEntries"][0]["id"] == 2


def test_silent_no_op_is_an_error(tmp_path):
    """A 204 that left the entry in place must not be reported as success."""
    client, _ = _client(tmp_path, actually_deletes=False)

    with pytest.raises(CronometerError, match="still in the diary"):
        client.delete_entries(["2"], entry_type="Biometric")
