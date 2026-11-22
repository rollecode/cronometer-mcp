"""get_food_log's compact detail level."""

from __future__ import annotations

import json

from cronometer_mcp import server


class FakeClient:
    def get_diary(self, day):
        return {
            "summary": {"macros": {"energy": 2000}, "consumed": {"total": 300.5}},
            "diary": [
                {"type": "Biometric", "amount": 50},
                {"type": "Exercise", "name": "Run", "time": "18:00:00", "minutes": 30, "calories": -200},
                {
                    "type": "Serving",
                    "servingId": 2,
                    "time": "12:00:00",
                    "name": "Sandwich",
                    "grams": 100,
                    "nutrients": [{"id": 208, "amount": 300.5}, {"id": 203, "amount": 5.04}],
                },
                {"type": "Serving", "servingId": 1, "time": "08:00:00", "grams": 200},
            ],
        }

    def enrich_diary_servings(self, diary):
        return diary

    def get_consumed_nutrients(self, day, include_untracked=True):
        nutrients = [{"id": 208, "amount": 300.5}, {"id": 301, "amount": 25}]
        if include_untracked:
            nutrients.append({"id": 269, "amount": 20.5})
        return {"macros": {}, "nutrients": nutrients}


def _read(monkeypatch, **kwargs):
    monkeypatch.setattr(server, "_get_client", FakeClient)
    return json.loads(server.get_food_log("2026-01-02", **kwargs))


def test_compact_log_keeps_rows_and_seven_totals(monkeypatch):
    log = _read(monkeypatch, detail="compact", include_untracked=False)

    assert log["energy_summary"]["remaining_kcal"] == 1700
    assert log["totals"] == {
        "energy": 300.5, "protein": None, "sodium": None, "sugars": 20.5,
        "saturated": None, "water": None, "caffeine": None,
    }
    assert log["entries"] == [
        {"id": 1, "time": "08:00", "name": None, "grams": 200, "kcal": None, "protein": None},
        {"id": 2, "time": "12:00", "name": "Sandwich", "grams": 100, "kcal": 300.5, "protein": 5.0},
    ]
    assert log["exercises"] == [{"time": "18:00", "name": "Run", "minutes": 30, "kcal": -200}]
    assert "diary" not in log


def test_full_log_stays_the_default(monkeypatch):
    log = _read(monkeypatch)

    assert "diary" in log
    assert "nutrition_summary" in log
