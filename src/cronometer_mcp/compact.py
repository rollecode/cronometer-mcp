"""The short form of a diary day."""

from enum import IntEnum, StrEnum

_TIME_CHARS = len("HH:MM")


class LogDetail(StrEnum):
    FULL = "full"
    COMPACT = "compact"


class _Nutrient(IntEnum):
    ENERGY = 208
    PROTEIN = 203
    SODIUM = 307
    SUGARS = 269
    SATURATED = 606
    WATER = 255
    CAFFEINE = 262


def _amounts(nutrients: list[dict] | None) -> dict[int, float]:
    return {
        n["id"]: round(n["amount"], 1)
        for n in nutrients or []
        if n.get("amount") is not None
    }


def _clock(entry: dict) -> str:
    return (entry.get("time") or "")[:_TIME_CHARS]


def _food_row(entry: dict) -> dict:
    eaten = _amounts(entry.get("nutrients"))

    return {
        "id": entry.get("servingId"),
        "time": _clock(entry),
        "name": entry.get("name"),
        "grams": entry.get("grams"),
        "kcal": eaten.get(_Nutrient.ENERGY),
        "protein": eaten.get(_Nutrient.PROTEIN),
    }


def _exercise_row(entry: dict) -> dict:
    return {
        "time": _clock(entry),
        "name": entry.get("name"),
        "minutes": entry.get("minutes"),
        "kcal": entry.get("calories"),
    }


def compact_day(diary: dict | None, nutrients: list[dict]) -> dict:
    entries = sorted((diary or {}).get("diary") or [], key=_clock)
    totals = _amounts(nutrients)

    return {
        "totals": {n.name.lower(): totals.get(n) for n in _Nutrient},
        "entries": [_food_row(e) for e in entries if e.get("type") == "Serving"],
        "exercises": [_exercise_row(e) for e in entries if e.get("type") == "Exercise"],
    }
