"""Tests that update_custom_food stores nutrients on the same basis as create.

create_custom_food takes per-serving amounts and divides by the serving weight
because Cronometer stores per 100 g. update_custom_food took the same
per-serving amounts and wrote them through unscaled, so editing a 455 g food
multiplied every diary entry of it by 4,55.
"""

from __future__ import annotations

from pathlib import Path

from cronometer_mcp.client import CronometerClient


def _client(tmp_path: Path, food: dict) -> tuple[CronometerClient, list[dict]]:
    client = CronometerClient(session_path=tmp_path / "session.json")
    client._user_id = 123
    client._token = "TOKEN"
    saved: list[dict] = []

    client.get_food = lambda food_id: food  # type: ignore[method-assign]
    client._save_food = lambda f, *, keep_measures=True: (  # type: ignore[method-assign]
        saved.append(f) or f
    )
    # The real one fetches the catalog; energy is the only name these need.
    client.resolve_nutrients = lambda values: [  # type: ignore[method-assign]
        {"id": 208, "amount": float(v)} for v in values.values()
    ]
    return client, saved


def _amount(food: dict, nutrient_id: int) -> float:
    return next(n["amount"] for n in food["nutrients"] if n["id"] == nutrient_id)


def _food(serving_grams: float, *, measure_id: int = 55) -> dict:
    return {
        "id": 1,
        "owner": 123,
        "name": "Test food",
        "defaultMeasureId": measure_id,
        "measures": [
            {
                "id": measure_id,
                "name": "1 serving",
                "value": serving_grams,
                "amount": 1.0,
                "type": "Atomic",
            }
        ],
        "nutrients": [{"id": 208, "amount": 100.0}],
    }


def test_nutrients_are_scaled_to_per_100g(tmp_path):
    """988,7 kcal for a 455 g pizza is 217,3 kcal per 100 g in storage."""
    client, saved = _client(tmp_path, _food(455.0))

    client.update_custom_food(1, nutrients={"energy": 988.7})

    assert _amount(saved[0], 208) == round(988.7 * 100 / 455, 4)


def test_a_100g_serving_is_unchanged(tmp_path):
    """The default serving size is already the storage basis."""
    client, saved = _client(tmp_path, _food(100.0))

    client.update_custom_food(1, nutrients={"energy": 250.0})

    assert _amount(saved[0], 208) == 250.0


def test_new_serving_weight_applies_to_the_same_call(tmp_path):
    """Correcting the weight and the nutrients together uses the new weight."""
    client, saved = _client(tmp_path, _food(400.0))

    client.update_custom_food(
        1,
        nutrients={"energy": 988.7},
        measures=[{"measure_id": 55, "grams": 455.0}],
    )

    assert saved[0]["measures"][0]["value"] == 455.0
    assert _amount(saved[0], 208) == round(988.7 * 100 / 455, 4)


def test_serving_basis_is_the_default_measure(tmp_path):
    """With several measures, per-serving means the food's default one."""
    food = _food(50.0, measure_id=77)
    food["measures"].append(
        {"id": 88, "name": "1 pussi", "value": 200.0, "amount": 1.0, "type": "Atomic"}
    )
    client, saved = _client(tmp_path, food)

    client.update_custom_food(1, nutrients={"energy": 180.0})

    assert _amount(saved[0], 208) == round(180.0 * 100 / 50, 4)


def test_round_trip_matches_create(tmp_path):
    """Editing a value to what it already was must not change what is stored."""
    created = {"id": 208, "amount": round(988.7 * 100 / 455, 4)}
    food = _food(455.0)
    food["nutrients"] = [created]
    client, saved = _client(tmp_path, food)

    client.update_custom_food(1, nutrients={"energy": 988.7})

    assert _amount(saved[0], 208) == created["amount"]
