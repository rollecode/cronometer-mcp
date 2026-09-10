"""A food read back and written again must keep the same nutrition.

get_food_details reported Cronometer's stored per-100 g rows while
add_custom_food and update_custom_food both take per-serving amounts, so
feeding a read straight back into an edit multiplied a food with a 1 g measure
by 100. Reading and writing have to speak the same unit.
"""

from __future__ import annotations

from pathlib import Path

from cronometer_mcp.client import CronometerClient

ENERGY_ID = 208
PROTEIN_ID = 203


def _client(tmp_path: Path) -> tuple[CronometerClient, list[dict]]:
    client = CronometerClient(session_path=tmp_path / "session.json")
    client._user_id = 123
    client._token = "TOKEN"
    sent: list[dict] = []

    client._request = lambda endpoint, payload, **kw: (  # type: ignore[method-assign]
        sent.append({"endpoint": endpoint, "payload": payload}) or {"id": 9001}
    )
    client.nutrient_index = lambda: {  # type: ignore[method-assign]
        "energy": {"id": ENERGY_ID, "name": "Energy", "unit": "kcal", "category": "General"},
        "protein": {"id": PROTEIN_ID, "name": "Protein", "unit": "g", "category": "General"},
    }
    return client, sent


def _stored_food(per_100g: dict[int, float], serving_grams: float) -> dict:
    return {
        "id": 9001,
        "owner": 123,
        "name": "Juice",
        "defaultMeasureId": 55,
        "measures": [
            {"id": 55, "name": "ml", "value": serving_grams, "amount": 1.0, "type": "Atomic"}
        ],
        "nutrients": [{"id": nid, "amount": a} for nid, a in per_100g.items()],
    }


def _kcal_for(food: dict, grams: float) -> float:
    per_100g = next(n["amount"] for n in food["nutrients"] if n["id"] == ENERGY_ID)
    return per_100g * grams / 100.0


def test_create_scales_a_one_gram_serving(tmp_path):
    """0,5 kcal per ml is 50 kcal per 100 g, so 200 ml is 100 kcal."""
    client, sent = _client(tmp_path)

    client.create_custom_food(
        "Juice", {"energy": 0.5}, serving_name="ml", serving_grams=1.0
    )

    written = sent[0]["payload"]["data"]["nutrients"]
    stored = _stored_food({n["id"]: n["amount"] for n in written}, 1.0)
    assert _kcal_for(stored, 200) == 100.0


def test_details_report_per_serving_not_per_100g(tmp_path):
    """The read has to be in the unit the write tools accept."""
    client, _ = _client(tmp_path)
    client.get_food = lambda food_id: _stored_food(  # type: ignore[method-assign]
        {ENERGY_ID: 50.0, PROTEIN_ID: 2.0}, 1.0
    )

    details = client.get_food_details(9001)

    assert details["serving_grams"] == 1.0
    assert details["nutrients"]["energy"] == 0.5
    assert details["nutrients"]["protein"] == 0.02


def test_read_modify_write_keeps_the_same_nutrition(tmp_path):
    """Writing back exactly what was read must not change a single value."""
    client, _sent = _client(tmp_path)
    food = _stored_food({ENERGY_ID: 50.0}, 1.0)
    client.get_food = lambda food_id: food  # type: ignore[method-assign]
    saved: list[dict] = []
    client._save_food = lambda f, *, keep_measures=True: (  # type: ignore[method-assign]
        saved.append(f) or f
    )

    details = client.get_food_details(9001)
    client.update_custom_food(9001, nutrients=details["nutrients"])

    assert _kcal_for(saved[0], 200) == 100.0
