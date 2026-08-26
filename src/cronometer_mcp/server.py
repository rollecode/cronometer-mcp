"""MCP server for Cronometer, using the API the Android app uses."""

import importlib.metadata
import json
import logging
import os
from datetime import date, datetime, timedelta
from datetime import time as dtime

from mcp.server.fastmcp import FastMCP
from mcp.types import Icon

from .client import CronometerClient

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

try:
    __version__ = importlib.metadata.version("cronometer-mcp")
except importlib.metadata.PackageNotFoundError:  # running from a source tree
    __version__ = "0.0.0"

# Advertised in the initialize response per the MCP icons spec, so a client can
# badge the connector with the Cronometer mark rather than guessing from the
# hostname. Three sizes because the spec has clients pick the one that fits
# their UI, and downscaling a single 256px asset to a 16px chip looks it.
# PNG throughout: it is one of the two types an icon-rendering client MUST
# support, and the URLs are same-origin, which the spec asks for so the icon
# cannot leak a request to a third party.
# Ref: https://github.com/modelcontextprotocol/modelcontextprotocol/issues/1040#issuecomment-3967699520
_ICON_BASE = os.getenv("MCP_PUBLIC_URL", "").rstrip("/")
_ICON_SIZES = (48, 96, 256)

mcp = FastMCP(
    "cronometer",
    icons=(
        [
            Icon(
                src=f"{_ICON_BASE}/icon.png"
                if size == 256
                else f"{_ICON_BASE}/icon-{size}.png",
                mimeType="image/png",
                sizes=[f"{size}x{size}"],
            )
            for size in _ICON_SIZES
        ]
        if _ICON_BASE
        else None
    ),
    website_url=_ICON_BASE or None,
    instructions=(
        "Read and write a Cronometer food diary: search foods, add and change "
        "diary entries, read daily nutrients and goals, record measurements, "
        "exercise and fasts. Use search_foods to find a food, get_food_details "
        "for its nutrients and serving sizes, add_food_entry to log a meal, "
        "and get_food_log to see what was eaten. Notes, measurements and "
        "exercise entries can be added and changed but not deleted."
    ),
)

# FastMCP has no version argument, and the server underneath falls back to the
# MCP SDK's own version, so initialize was reporting the SDK's number as ours.
mcp._mcp_server.version = __version__

_client: CronometerClient | None = None


def _get_client() -> CronometerClient:
    global _client
    if _client is None:
        _client = CronometerClient()
    return _client


def _parse_date(d: str | None) -> date | None:
    if d is None:
        return None
    return date.fromisoformat(d)


def _parse_time(t: str | None) -> dtime | None:
    """Parse a diary timestamp given as HH:MM or HH:MM:SS."""
    if t is None:
        return None
    try:
        return dtime.fromisoformat(t)
    except ValueError:
        raise ValueError(
            f"Invalid time '{t}'. Use HH:MM or HH:MM:SS, e.g. 10:15."
        ) from None


def _ok(data: dict) -> str:
    """Wrap a successful response."""
    return json.dumps({"status": "success", **data}, indent=2)


_WRITE = {
    "readOnlyHint": False,
    "destructiveHint": False,
    "idempotentHint": True,
    "openWorldHint": True,
}
_DESTRUCTIVE = {**_WRITE, "destructiveHint": True}


def _err(e: Exception) -> str:
    """Wrap an error response with actionable messages."""
    import httpx

    if isinstance(e, httpx.HTTPStatusError):
        status = e.response.status_code
        if status == 401 or status == 403:
            msg = "Authentication failed. Cronometer session may have expired -- try again."
        elif status == 429:
            msg = "Rate limit exceeded. Wait a few minutes before retrying."
        elif status == 404:
            msg = f"Resource not found (HTTP {status})."
        else:
            msg = f"Cronometer API error (HTTP {status})."
    elif isinstance(e, httpx.TimeoutException):
        msg = "Request timed out. Cronometer may be slow -- try again."
    elif isinstance(e, httpx.ConnectError):
        msg = "Could not connect to Cronometer. Check network connectivity."
    else:
        msg = f"{type(e).__name__}: {e}"

    return json.dumps({"status": "error", "message": msg})


# ------------------------------------------------------------------
# Diary: read
# ------------------------------------------------------------------


@mcp.tool(
    annotations={
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    }
)
def get_food_log(date: str | None = None, include_untracked: bool = True) -> str:
    """Get all diary entries for a given date.

    Returns every food entry logged for the day. Each "Serving" entry is
    enriched (best-effort) with the food's name, source, the serving measure
    (unit name and grams per unit), the number of servings, and that food's
    own nutrient profile scaled to the amount eaten. Non-food entries
    (exercise, biometrics) carry their own name.

    Note: the per-entry "nutrients" are each food's individual contribution,
    which is distinct from the day-level nutrition_summary aggregate below.

    Also returns a top-level energy_summary field with pre-computed
    values most relevant to the user:

      - total_target_kcal: daily calorie target dynamically adjusted
        for expenditure and weight goal (equivalent to Cronometer's
        "Total Target" in the Energy Summary screen)
      - consumed_kcal: total calories consumed
      - remaining_kcal: calories remaining to stay on target
        (total_target_kcal - consumed_kcal). Always report this
        when summarizing the user's day. Prefer this over manually
        deriving values from the burn breakdown fields.

    Also returns a nutrition_summary field with consumed totals for every
    nutrient eaten that day:

      - macros: flat macro totals (energy, protein, carbs, net_carbs, fat,
        fiber, alcohol)
      - nutrients: every nutrient with amount, unit and `tracked`, which says
        whether it has a target set in Cronometer. Untracked ones were still
        eaten; they just have nothing to measure against, so report them as
        plain figures and never as over or under target.

    Args:
        date: Date as YYYY-MM-DD (defaults to today).
        include_untracked: Leave true for everything eaten. False restricts the
            summary to nutrients with targets, matching the app's own summary.
    """
    try:
        client = _get_client()
        day = _parse_date(date)
        data = client.get_diary(day)
        data = client.enrich_diary_servings(data)

        summary = (data or {}).get("summary") or {}
        target = (summary.get("macros") or {}).get("energy")
        consumed = (summary.get("consumed") or {}).get("total")
        energy_summary: dict | None = None
        if target is not None and consumed is not None:
            energy_summary = {
                "total_target_kcal": target,
                "consumed_kcal": consumed,
                "remaining_kcal": round(target - consumed),
            }

        nutrition_summary = client.get_consumed_nutrients(
            day, include_untracked=include_untracked
        )

        return _ok(
            {
                "date": date or str(date_module_today()),
                "energy_summary": energy_summary,
                "nutrition_summary": nutrition_summary,
                "diary": data,
            }
        )
    except Exception as e:
        return _err(e)


# ------------------------------------------------------------------
# Diary: write
# ------------------------------------------------------------------


@mcp.tool(
    annotations={
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": False,
        "openWorldHint": True,
    }
)
def add_food_entry(
    food_id: int,
    measure_id: int,
    grams: float,
    date: str | None = None,
    translation_id: int = 0,
    diary_group: str = "auto",
    time: str | None = None,
) -> str:
    """Add a food entry to the Cronometer diary.

    Use search_foods to find food_id and measure_id, then
    get_food_details to confirm serving sizes and gram weights.

    Args:
        food_id: Numeric food ID from search_foods results.
        measure_id: Measure/unit ID from get_food_details.
        grams: Weight of the serving in grams. Real grams for recipes too:
            the conversion to Cronometer's batch units happens here.
        date: Date to log as YYYY-MM-DD (defaults to today).
        translation_id: Translation ID from search results (usually 0).
        diary_group: Meal slot -- one of "auto", "breakfast", "lunch",
                     "dinner", "snacks" (case-insensitive, default "auto").
        time: Time of day as HH:MM or HH:MM:SS. Defaults to now. Pass the real
            eating time when logging after the fact; an "auto" diary_group
            then follows that hour instead of the current one.
    """
    try:
        group_map = {
            "auto": 0,
            "breakfast": 1,
            "lunch": 2,
            "dinner": 3,
            "snacks": 4,
        }
        group_key = diary_group.strip().lower()
        group_int = group_map.get(group_key)
        if group_int is None:
            return _err(
                ValueError(
                    f"Invalid diary_group '{diary_group}'. "
                    "Must be one of: auto, breakfast, lunch, dinner, snacks."
                )
            )

        client = _get_client()
        day = _parse_date(date)
        result = client.add_serving(
            food_id=food_id,
            measure_id=measure_id,
            grams=grams,
            translation_id=translation_id,
            day=day,
            diary_group=group_int,
            time=_parse_time(time),
        )
        return _ok(
            {
                "entry": result,
                "note": "Use the serving ID to remove this entry with remove_food_entry.",
            }
        )
    except Exception as e:
        return _err(e)


@mcp.tool(
    annotations={
        "readOnlyHint": False,
        "destructiveHint": True,
        "idempotentHint": True,
        "openWorldHint": True,
    }
)
def remove_food_entry(
    entry_ids: list[str],
    date: str | None = None,
) -> str:
    """Remove one or more food entries from the Cronometer diary.

    Use get_food_log to find entry IDs.

    Args:
        entry_ids: List of serving/entry IDs to remove.
        date: Date the entries belong to as YYYY-MM-DD (defaults to today).
    """
    try:
        client = _get_client()
        day = _parse_date(date)
        result = client.delete_entries(entry_ids, day)
        return _ok(
            {
                "removed": result.get("removed", []),
                "count": result.get("count", 0),
                "date": date or str(date_module_today()),
            }
        )
    except Exception as e:
        return _err(e)


# ------------------------------------------------------------------
# Diary: management
# ------------------------------------------------------------------


@mcp.tool(
    annotations={
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    }
)
def mark_day_complete(date: str, complete: bool = True) -> str:
    """Mark a diary day as complete or incomplete.

    Args:
        date: Date to mark as YYYY-MM-DD.
        complete: True to mark complete, False for incomplete.
    """
    try:
        client = _get_client()
        day = _parse_date(date)
        result = client.mark_day_complete(day, complete)
        status = "complete" if complete else "incomplete"
        return _ok(
            {
                "date": date,
                "marked": status,
                "result": result,
            }
        )
    except Exception as e:
        return _err(e)


@mcp.tool(
    annotations={
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": False,
        "openWorldHint": True,
    }
)
def copy_day(date: str | None = None) -> str:
    """Copy all diary entries from the previous day to the given date.

    Additive -- does not remove existing entries on the destination date.

    Args:
        date: Destination date as YYYY-MM-DD (defaults to today).
    """
    try:
        client = _get_client()
        day = _parse_date(date)
        result = client.copy_day(to_day=day)
        return _ok(
            {
                "destination_date": date or str(date_module_today()),
                "result": result,
            }
        )
    except Exception as e:
        return _err(e)


# ------------------------------------------------------------------
# Nutrition
# ------------------------------------------------------------------


@mcp.tool(
    annotations={
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    }
)
def get_daily_nutrition(date: str | None = None, include_untracked: bool = True) -> str:
    """Get daily nutrition totals for every nutrient eaten that day.

    The response has:

      - summary: flat macro totals (energy, protein, carbs, net_carbs, fat,
        fiber, alcohol). A value is null if nothing that day contained it.
      - nutrients: each with id, name, amount, unit, category, confidence and
        `tracked`.
      - tracked_count and untracked_count.

    `tracked` says whether that nutrient has a target set in Cronometer.
    Untracked nutrients are still eaten and still counted here; they simply have
    nothing to measure against, and Cronometer's own summary leaves them out. So
    an absent nutrient means none was eaten, rather than none being tracked.

    Report an untracked amount as a plain figure. It has no target, so never
    describe it as over, under or on track, and offer set_nutrient_target if a
    target would be useful.

    Args:
        date: Date as YYYY-MM-DD (defaults to today).
        include_untracked: Leave true for everything eaten. False restricts the
            response to nutrients with targets, matching the app's own summary.
    """
    try:
        client = _get_client()
        day = _parse_date(date)
        data = client.get_consumed_nutrients(day, include_untracked=include_untracked)
        return _ok(
            {
                "date": date or str(date_module_today()),
                "summary": data["macros"],
                "nutrients": data["nutrients"],
                "tracked_count": data["tracked_count"],
                "untracked_count": data["untracked_count"],
            }
        )
    except Exception as e:
        return _err(e)


@mcp.tool(
    annotations={
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    }
)
def get_nutrition_scores(date: str | None = None) -> str:
    """Get nutrition scores with per-nutrient consumed amounts and category grades.

    Returns category scores (All Targets, Vitamins, Minerals, Electrolytes,
    Antioxidants, Immune Support, Metabolism, Bone Health) with the actual
    consumed amount and confidence level for each nutrient.

    This is Cronometer's own scoring, so it covers only nutrients with a target;
    scoring one without a target would have nothing to score against. Use it to
    see how close each nutrient is to its target, and get_daily_nutrition when
    you need everything that was actually eaten.

    Args:
        date: Date as YYYY-MM-DD (defaults to today).
    """
    try:
        client = _get_client()
        day = _parse_date(date)
        data = client.get_nutrition_scores(day)
        return _ok(
            {
                "date": date or str(date_module_today()),
                "scores": data,
            }
        )
    except Exception as e:
        return _err(e)


# ------------------------------------------------------------------
# Food search and details
# ------------------------------------------------------------------


@mcp.tool(
    annotations={
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    }
)
def search_foods(query: str) -> str:
    """Search Cronometer's food database by name.

    Returns matching foods with their IDs and source information.
    Use the food_id and measure_id from results with add_food_entry,
    or pass food_id to get_food_details for full nutrition info.

    Args:
        query: Food name or keyword (e.g. "eggs", "chicken breast").
    """
    try:
        client = _get_client()
        foods = client.search_food(query)

        # Slim down results to the most useful fields
        results = []
        for f in foods:
            results.append(
                {
                    "food_id": f.get("id"),
                    "name": f.get("name"),
                    "source": f.get("source"),
                    "measure_id": f.get("measureId"),
                    "translation_id": f.get("translationId"),
                    "measure_display": f.get("measureDisplayName"),
                    "score": f.get("score"),
                }
            )

        return _ok(
            {
                "query": query,
                "count": len(results),
                "foods": results,
            }
        )
    except Exception as e:
        return _err(e)


@mcp.tool(
    annotations={
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    }
)
def get_food_details(food_id: int) -> str:
    """Get detailed food information including nutrition and serving sizes.

    Use this after search_foods to get the full nutrient profile and
    available measure_ids needed for add_food_entry.

    Args:
        food_id: Food ID from search_foods results.
    """
    try:
        client = _get_client()
        data = client.get_food(food_id)

        # Extract measures for easy reference
        measures = []
        for m in data.get("measures", []):
            measures.append(
                {
                    "measure_id": m.get("id"),
                    "name": m.get("name"),
                    "grams": m.get("value"),
                }
            )

        return _ok(
            {
                "food_id": data.get("id"),
                "name": data.get("name"),
                "default_measure_id": data.get("defaultMeasureId"),
                "measures": measures,
                "nutrients": data.get("nutrients", []),
            }
        )
    except Exception as e:
        return _err(e)


# ------------------------------------------------------------------
# Custom food creation
# ------------------------------------------------------------------


@mcp.tool(
    annotations={
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": False,
        "openWorldHint": True,
    }
)
def add_custom_food(
    name: str,
    nutrients: dict[str, float],
    serving_name: str = "1 serving",
    serving_grams: float = 100.0,
    label_type: str = "AMERICAN_2016",
    notes: str | None = None,
) -> str:
    """Create a custom food with any nutrients you have, from 1 to all 94.

    Amounts are for one whole serving, each in that nutrient's own unit. Call
    list_nutrients for the accepted names and their units. Only pass the
    nutrients you actually know: a nutrient you leave out stays blank in
    Cronometer, while passing 0 states the food contains none of it, and the
    app treats those differently. An unrecognised name is an error, so nothing
    is silently dropped from a food that then looks complete.

    Two label conveniences: energy_kj is converted to calories, salt_g to
    sodium. Pass either one or its underlying nutrient, not both.

    After creation, use the returned food_id with add_food_entry to log it.

    Args:
        name: Food name.
        nutrients: Nutrient name to amount per serving, e.g.
            {"energy": 250, "protein": 12.5, "vitamin_c": 30, "b12_cobalamin": 1.2}.
        serving_name: Name for the serving size (default "1 serving").
        serving_grams: Weight of one serving in grams (default 100).
        label_type: "AMERICAN_2016" or "EUROPEAN".
        notes: Free-text note stored on the food.
    """
    try:
        client = _get_client()
        result = client.create_custom_food(
            name,
            nutrients,
            serving_name=serving_name,
            serving_grams=serving_grams,
            label_type=label_type,
            notes=notes,
        )

        # Fetch back to get the server-assigned measure_id
        food_data = client.get_food(result["food_id"])
        result["measure_id"] = food_data.get("defaultMeasureId")

        return _ok(
            {
                "food_id": result["food_id"],
                "measure_id": result["measure_id"],
                "name": name,
                "nutrients_set": len(nutrients),
                "note": "Use food_id and measure_id with add_food_entry to log this food.",
            }
        )
    except Exception as e:
        return _err(e)


_READ = {
    "readOnlyHint": True,
    "destructiveHint": False,
    "idempotentHint": True,
    "openWorldHint": True,
}


@mcp.tool(annotations=_READ)
def get_recent_foods() -> str:
    """Recently logged foods with how often each was logged.

    The fastest route for "log my usual": find the food here, then
    add_food_entry. Recipes are flagged so a whole batch is not logged as one
    portion by mistake.
    """
    try:
        return _ok({"foods": _get_client().get_recent_foods()})
    except Exception as e:
        return _err(e)


@mcp.tool(annotations=_READ)
def get_streak(date: str | None = None) -> str:
    """Diary logging streaks: current run of fully logged days, and the record.

    Args:
        date: Day to count back from as YYYY-MM-DD (defaults to today).
    """
    try:
        return _ok(_get_client().get_streak(_parse_date(date)))
    except Exception as e:
        return _err(e)


@mcp.tool(annotations=_READ)
def get_profile() -> str:
    """The account profile: birthdate, gender, timezone and language."""
    try:
        return _ok({"profile": _get_client().get_profile()})
    except Exception as e:
        return _err(e)


@mcp.tool(annotations=_WRITE)
def create_recipe(
    name: str,
    ingredients: list[dict],
    servings: float = 1.0,
    notes: str | None = None,
    recipe_id: int | None = None,
    serving_type: str = "weight",
    cooked_grams: float | None = None,
) -> str:
    """Create a recipe from ingredients, or update one by passing recipe_id.

    Cronometer sums the nutrients from the ingredients itself, so unlike
    add_custom_food you give foods and amounts, not nutrient values. Use
    search_foods to find each ingredient's food_id and measure_id first.

    Cronometer locks a recipe's serving type when it is created and it cannot
    be changed afterwards, so choose deliberately:

    - "weight" (default) measures the recipe in grams. Portions log as plain
      grams in every client, including the mobile app's own entry screen. The
      ingredient list is recorded in the notes rather than as editable
      ingredients, because Cronometer will not compute a correct weight from
      ingredients that use non-weight measures.
    - "servings" keeps an editable ingredient list in Cronometer, but the
      mobile app then offers only a 1 g serving and hides the amount field.
      Logging through this server is still correct in grams.

    cooked_grams is the weight of the finished dish. Give it whenever the food
    was baked or simmered: nutrients are stored per 100 g, and a dish that lost
    water is denser than its raw ingredients, so without it a portion weighed
    off the plate logs too little.

    Updating with recipe_id replaces the whole ingredient list, so pass every
    ingredient, not only new ones. Recipes are removed with retire_custom_food,
    the same as custom foods.

    Args:
        name: Recipe name.
        ingredients: List of {"food_id": int, "grams": float,
            "measure_id": int (optional)}.
        servings: How many portions the batch makes.
        notes: Free-text note stored on the recipe.
        recipe_id: Existing recipe to update in place.
        serving_type: "weight" or "servings". Cannot be changed later.
        cooked_grams: Weight of the finished dish, if it lost water in cooking.
    """
    try:
        client = _get_client()
        result = client.create_recipe(
            name,
            ingredients,
            servings=servings,
            notes=notes,
            recipe_id=recipe_id or 0,
            serving_type=serving_type,
            cooked_grams=cooked_grams,
        )
        food = client.get_food(result["food_id"])
        measures = [
            {"measure_id": m["id"], "name": m["name"], "grams": m["value"]}
            for m in food.get("measures", [])
        ]
        return _ok(
            {
                **result,
                "servings": servings,
                "measures": measures,
                "note": "Log one portion with add_food_entry using the serving measure.",
            }
        )
    except Exception as e:
        return _err(e)


@mcp.tool(annotations=_READ)
def list_custom_foods(query: str = "", include_retired: bool = False) -> str:
    """Every custom food and recipe you own, with no database results mixed in.

    Leave query empty for the whole library. This is the way to audit it: to
    find, say, every food whose name lost its Finnish characters, list them all
    and read the names, then fix each with update_custom_food.

    Retired foods are hidden by Cronometer's own library listing, so
    include_retired cannot bring them back; it only affects rows already
    returned.

    Args:
        query: Narrow the list by name. Empty lists everything.
        include_retired: Keep retired foods in the result when they appear.
    """
    try:
        foods = _get_client().list_own_foods(query, include_retired)
        return _ok({"count": len(foods), "foods": foods})
    except Exception as e:
        return _err(e)


@mcp.tool(annotations=_READ)
def list_recipes(include_retired: bool = False) -> str:
    """Every recipe you own, with its serving type.

    serving_type says which kind each one is: "weight" logs in grams
    everywhere, "servings" keeps an editable ingredient list but shows a 1 g
    serving in the mobile app. It is fixed at creation and cannot be changed.

    Args:
        include_retired: Keep retired recipes in the result when they appear.
    """
    try:
        foods = [
            f for f in _get_client().list_own_foods("", include_retired)
            if f["is_recipe"]
        ]
        return _ok({"count": len(foods), "recipes": foods})
    except Exception as e:
        return _err(e)


@mcp.tool(annotations=_READ)
def find_entries_by_food(
    food_id: int, start_date: str | None = None, end_date: str | None = None
) -> str:
    """Every diary entry that references a food, with dates and amounts.

    Use before replacing or retiring a food, so its entries can be moved rather
    than left pointing at something retired.

    Cronometer cannot search entries by food, so this reads the diary one day
    at a time and the range costs a request per day. It defaults to the last 30
    days; widen it deliberately.

    Args:
        food_id: The food to look for.
        start_date: First day as YYYY-MM-DD (defaults to 30 days back).
        end_date: Last day as YYYY-MM-DD (defaults to today).
    """
    try:
        client = _get_client()
        entries = client.find_entries_by_food(
            food_id, _parse_date(start_date), _parse_date(end_date)
        )
        return _ok(
            {
                "food_id": food_id,
                "count": len(entries),
                "total_grams": round(sum(e["grams"] or 0 for e in entries), 1),
                "entries": entries,
            }
        )
    except Exception as e:
        return _err(e)


@mcp.tool(annotations=_WRITE)
def update_custom_food(
    food_id: int,
    name: str | None = None,
    notes: str | None = None,
    nutrients: dict[str, float] | None = None,
    measures: list[dict] | None = None,
) -> str:
    """Edit one of your custom foods in place, keeping its diary entries.

    Only what you pass changes. Entries already logged stay attached to this
    same food and their nutrition follows the edit, so a typo or a wrong
    nutrient can be fixed without re-logging anything.

    Nutrients are merged into the existing profile, so correcting one value
    leaves the rest alone. Call list_nutrients for the accepted names.

    Args:
        food_id: The custom food to edit.
        name: New name.
        notes: New note text.
        nutrients: Nutrient name to amount per serving, merged in.
        measures: [{"measure_id": int, "name": str, "grams": float}] to fix a
            wrongly weighted measure. name and grams are each optional.
            Leave measure_id out to ADD a serving size instead, giving name and
            grams: that is how a food gets a per-piece measure such as
            "1 karkki" or "1 viipale" alongside plain grams, so it can be logged
            by the count as well as by weight.
    """
    try:
        result = _get_client().update_custom_food(
            food_id, name=name, notes=notes, nutrients=nutrients, measures=measures
        )
        return _ok(result)
    except Exception as e:
        return _err(e)


@mcp.tool(annotations=_WRITE)
def update_recipe(
    food_id: int,
    name: str | None = None,
    notes: str | None = None,
    ingredients: list[dict] | None = None,
    cooked_grams: float | None = None,
) -> str:
    """Edit one of your recipes in place, keeping its diary entries.

    Only what you pass changes, and the serving type never does: Cronometer
    fixes it at creation. Passing ingredients replaces the whole list, so send
    every ingredient rather than only the new ones.

    Args:
        food_id: The recipe to edit.
        name: New name.
        notes: New note text.
        ingredients: Full replacement list of
            {"food_id": int, "grams": float, "measure_id": int (optional)}.
        cooked_grams: New finished weight. Weight-based recipes only, and it
            needs the ingredients too, since the nutrition is recomputed.
    """
    try:
        result = _get_client().update_recipe(
            food_id,
            name=name,
            notes=notes,
            ingredients=ingredients,
            cooked_grams=cooked_grams,
        )
        return _ok(result)
    except Exception as e:
        return _err(e)


@mcp.tool(annotations=_DESTRUCTIVE)
def retire_custom_food(food_id: int, retired: bool = True) -> str:
    """Retire a custom food so it stops being offered for new entries.

    This is how Cronometer removes a food; there is no delete. Diary entries
    that already use it keep working. Pass retired=False to bring it back.

    Args:
        food_id: The custom food's ID.
        retired: True to retire, False to restore.
    """
    try:
        _get_client().retire_custom_food(food_id, retired)
        return _ok({"food_id": food_id, "retired": retired})
    except Exception as e:
        return _err(e)


@mcp.tool(
    annotations={
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    }
)
def list_nutrients() -> str:
    """Every nutrient add_custom_food accepts, with its unit and category.

    Read from the account's own catalog, so it stays right as Cronometer adds
    nutrients. Use the returned keys for the add_custom_food nutrients dict.
    """
    try:
        index = _get_client().nutrient_index()
        by_category: dict[str, list[dict]] = {}
        for key, meta in sorted(index.items()):
            by_category.setdefault(meta["category"] or "Other", []).append(
                {"key": key, "name": meta["name"], "unit": meta["unit"]}
            )
        return _ok(
            {
                "count": len(index),
                "categories": by_category,
                "conveniences": {
                    "energy_kj": "kJ, converted to calories",
                    "salt_g": "g of salt, converted to sodium in mg",
                },
            }
        )
    except Exception as e:
        return _err(e)


# ------------------------------------------------------------------
# Macro targets
# ------------------------------------------------------------------


@mcp.tool(
    annotations={
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    }
)
def get_macro_targets() -> str:
    """Get current macro targets including weekly schedule and templates.

    Returns the weekly macro schedule (which template applies to each day)
    and all saved macro target templates with their values.
    """
    try:
        client = _get_client()
        schedules = client.get_macro_schedules()
        templates = client.get_macro_target_templates()
        return _ok(
            {
                "schedules": schedules,
                "templates": templates,
            }
        )
    except Exception as e:
        return _err(e)


# ------------------------------------------------------------------
# Fasting
# ------------------------------------------------------------------


@mcp.tool(
    annotations={
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    }
)
def get_fasting_history(
    start_date: str | None = None,
    end_date: str | None = None,
) -> str:
    """Get fasting history from Cronometer.

    Returns fasts within the date range including status, timestamps,
    and duration.

    Args:
        start_date: Start date as YYYY-MM-DD (defaults to 30 days ago).
        end_date: End date as YYYY-MM-DD (defaults to today).
    """
    try:
        client = _get_client()
        start = _parse_date(start_date)
        end = _parse_date(end_date)
        data = client.get_fasting_with_date_range(start, end)
        return _ok(
            {
                "start_date": start_date
                or str(date_module_today() - timedelta(days=30)),
                "end_date": end_date or str(date_module_today()),
                "fasting": data,
            }
        )
    except Exception as e:
        return _err(e)


@mcp.tool(
    annotations={
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    }
)
def get_fasting_stats() -> str:
    """Get aggregate fasting statistics.

    Returns total fasting hours, longest fast, average fast duration,
    and completed fast count.
    """
    try:
        client = _get_client()
        data = client.get_fasting_stats()
        return _ok({"stats": data})
    except Exception as e:
        return _err(e)


# ------------------------------------------------------------------
# Biometrics
# ------------------------------------------------------------------


@mcp.tool(
    annotations={
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    }
)
def list_biometrics() -> str:
    """List the biometric metrics tracked in Cronometer.

    Returns every metric type the account can record (Weight, Body Fat,
    Heart Rate, Blood Glucose, Waist Size, Sleep, blood panels, body
    measurements, etc.). Use the metric_id and a unit_id from the results
    with get_biometrics.
    """
    try:
        client = _get_client()
        metrics = client.get_metrics()

        # Slim down results to the fields needed to call get_biometrics
        results = []
        for m in metrics:
            results.append(
                {
                    "metric_id": m.get("id"),
                    "name": m.get("name"),
                    "units": [
                        {"unit_id": u.get("id"), "name": u.get("name")}
                        for u in m.get("units", [])
                    ],
                }
            )

        return _ok({"count": len(results), "metrics": results})
    except Exception as e:
        return _err(e)


@mcp.tool(
    annotations={
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    }
)
def get_biometrics(
    metric_id: int,
    unit_id: int,
    start_date: str | None = None,
    end_date: str | None = None,
) -> str:
    """Get a biometric time series such as weight or body fat from Cronometer.

    Returns the recorded values over the date range as a list of
    {day, value} points.

    Use list_biometrics to find metric_id and unit_id (e.g. Weight is
    metric_id 1, with unit_id 1 for kg or 2 for lbs).

    Args:
        metric_id: Numeric metric ID from list_biometrics.
        unit_id: Numeric unit ID from the metric's units in list_biometrics.
        start_date: Start date as YYYY-MM-DD (defaults to 30 days ago).
        end_date: End date as YYYY-MM-DD (defaults to today).
    """
    try:
        client = _get_client()
        data = client.get_biometrics(
            metric_id,
            unit_id,
            start=_parse_date(start_date),
            end=_parse_date(end_date),
        )
        return _ok(
            {
                "metric_id": metric_id,
                "unit_id": unit_id,
                "start_date": start_date
                or str(date_module_today() - timedelta(days=30)),
                "end_date": end_date or str(date_module_today()),
                "biometrics": data,
            }
        )
    except Exception as e:
        return _err(e)


# ------------------------------------------------------------------
# Diary: servings
# ------------------------------------------------------------------


@mcp.tool(annotations=_WRITE)
def edit_food_entry(
    entry_id: int,
    grams: float | None = None,
    time: str | None = None,
    date: str | None = None,
) -> str:
    """Change the amount or time of an already logged food entry.

    Use get_food_log to find entry IDs.

    Args:
        entry_id: The serving ID of the entry to change.
        grams: New amount in grams.
        time: New time as HH:MM or HH:MM:SS.
        date: Date the entry is on as YYYY-MM-DD (defaults to today).
    """
    try:
        client = _get_client()
        stamp = _parse_time(time)
        client.edit_serving(
            entry_id,
            grams=grams,
            time=None if stamp is None else f"{stamp.hour}:{stamp.minute}:{stamp.second}",
            day=_parse_date(date),
        )
        entry = client.find_entry(entry_id, "Serving", _parse_date(date))
        return _ok({"entry_id": entry_id, "grams": entry["grams"], "time": entry["time"]})
    except Exception as e:
        return _err(e)


# ------------------------------------------------------------------
# Diary: notes
# ------------------------------------------------------------------


@mcp.tool(annotations=_WRITE)
def add_note(text: str, date: str | None = None) -> str:
    """Add a note to a day in the Cronometer diary.

    Cronometer cannot delete notes, only rewrite them, so a note added here can
    be changed but only removed in the Cronometer app.

    Args:
        text: The note text.
        date: Date as YYYY-MM-DD (defaults to today).
    """
    try:
        result = _get_client().add_note(text, _parse_date(date))
        return _ok({"note_id": result.get("id"), "date": date or str(date_module_today())})
    except Exception as e:
        return _err(e)


@mcp.tool(annotations=_WRITE)
def edit_note(note_id: int, text: str, date: str | None = None) -> str:
    """Replace the text of an existing diary note.

    Args:
        note_id: The note ID, from get_food_log.
        text: The replacement text.
        date: Date the note is on as YYYY-MM-DD (defaults to today).
    """
    try:
        _get_client().edit_note(note_id, text, _parse_date(date))
        return _ok({"note_id": note_id, "text": text})
    except Exception as e:
        return _err(e)


# ------------------------------------------------------------------
# Diary: biometrics
# ------------------------------------------------------------------


@mcp.tool(annotations=_WRITE)
def add_biometric(
    metric_id: int,
    unit_id: int,
    amount: float,
    date: str | None = None,
) -> str:
    """Record a biometric measurement, such as weight or body fat.

    Use list_biometrics to find metric IDs and their valid unit IDs.
    Cronometer cannot delete measurements, only change their value, so fix a
    wrong one with edit_biometric or remove it in the Cronometer app.

    Args:
        metric_id: Metric to record, from list_biometrics.
        unit_id: Unit the amount is in, from that metric's units.
        amount: The measured value.
        date: Date as YYYY-MM-DD (defaults to today).
    """
    try:
        result = _get_client().add_biometric(
            metric_id, unit_id, amount, _parse_date(date)
        )
        return _ok(
            {
                "biometric_id": result.get("id"),
                "metric_id": metric_id,
                "amount": amount,
                "date": date or str(date_module_today()),
            }
        )
    except Exception as e:
        return _err(e)


@mcp.tool(annotations=_WRITE)
def edit_biometric(biometric_id: int, amount: float, date: str | None = None) -> str:
    """Change the value of a recorded biometric.

    Args:
        biometric_id: The biometric ID, from get_food_log.
        amount: The corrected value, in the unit the entry already uses.
        date: Date the entry is on as YYYY-MM-DD (defaults to today).
    """
    try:
        _get_client().edit_biometric(biometric_id, amount, _parse_date(date))
        return _ok({"biometric_id": biometric_id, "amount": amount})
    except Exception as e:
        return _err(e)


# ------------------------------------------------------------------
# Diary: exercise
# ------------------------------------------------------------------


@mcp.tool(annotations=_WRITE)
def add_exercise(
    name: str,
    minutes: int,
    calories_burned: float,
    date: str | None = None,
) -> str:
    """Log an exercise entry.

    Cronometer cannot delete exercise entries, only change them, so fix a wrong
    one with edit_exercise or remove it in the Cronometer app.

    Args:
        name: What the exercise was called.
        minutes: Duration in minutes.
        calories_burned: Calories burned, as a positive number.
        date: Date as YYYY-MM-DD (defaults to today).
    """
    try:
        result = _get_client().add_exercise(
            name, minutes, calories_burned, _parse_date(date)
        )
        return _ok(
            {
                "exercise_id": result.get("id"),
                "name": name,
                "minutes": minutes,
                "calories_burned": calories_burned,
                "date": date or str(date_module_today()),
            }
        )
    except Exception as e:
        return _err(e)


@mcp.tool(annotations=_WRITE)
def edit_exercise(
    exercise_id: int,
    minutes: int | None = None,
    calories_burned: float | None = None,
    date: str | None = None,
) -> str:
    """Change the duration or calorie burn of a logged exercise.

    Args:
        exercise_id: The exercise ID, from get_food_log.
        minutes: New duration in minutes.
        calories_burned: New burn, as a positive number.
        date: Date the entry is on as YYYY-MM-DD (defaults to today).
    """
    try:
        _get_client().edit_exercise(
            exercise_id,
            minutes=minutes,
            calories_burned=calories_burned,
            day=_parse_date(date),
        )
        return _ok({"exercise_id": exercise_id})
    except Exception as e:
        return _err(e)


# ------------------------------------------------------------------
# Fasting
# ------------------------------------------------------------------


@mcp.tool(annotations=_WRITE)
def add_fast(start: str, end: str | None = None, goal_hours: float = 16) -> str:
    """Record a fast.

    Args:
        start: When the fast started, as YYYY-MM-DD HH:MM.
        end: When it ended, same format. Omit for an ongoing fast.
        goal_hours: Target length in hours.
    """
    try:
        client = _get_client()
        tz = client._tzinfo()
        started = datetime.strptime(start, "%Y-%m-%d %H:%M").replace(tzinfo=tz)
        ended = (
            datetime.strptime(end, "%Y-%m-%d %H:%M").replace(tzinfo=tz)
            if end
            else None
        )
        result = client.add_fast(started, ended, goal_hours)
        return _ok({"fast_id": result.get("id"), "start": start, "end": end})
    except Exception as e:
        return _err(e)


@mcp.tool(annotations=_WRITE)
def edit_fast(
    fast_id: int,
    start: str | None = None,
    end: str | None = None,
    goal_hours: float | None = None,
) -> str:
    """Change a recorded fast, including ending one that is still open.

    Args:
        fast_id: The fast ID, from get_fasting_history.
        start: New start as YYYY-MM-DD HH:MM.
        end: New end as YYYY-MM-DD HH:MM.
        goal_hours: New target length in hours.
    """
    try:
        client = _get_client()
        tz = client._tzinfo()

        def parse(s: str) -> datetime:
            return datetime.strptime(s, "%Y-%m-%d %H:%M").replace(tzinfo=tz)

        client.edit_fast(
            fast_id,
            start=parse(start) if start else None,
            end=parse(end) if end else None,
            goal_hours=goal_hours,
        )
        return _ok({"fast_id": fast_id})
    except Exception as e:
        return _err(e)


@mcp.tool(annotations=_DESTRUCTIVE)
def delete_fast(fast_id: int) -> str:
    """Remove a recorded fast.

    Args:
        fast_id: The fast ID, from get_fasting_history.
    """
    try:
        _get_client().delete_fast(fast_id)
        return _ok({"deleted": fast_id})
    except Exception as e:
        return _err(e)


# ------------------------------------------------------------------
# Targets
# ------------------------------------------------------------------


@mcp.tool(
    annotations={
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    }
)
def get_targets() -> str:
    """Nutrient targets for the account, as shown beside the diary totals."""
    try:
        client = _get_client()
        defs = client.get_nutrient_definitions()
        rows = []
        for row in client.get_targets().get("targets", []):
            meta = defs.get(row.get("id"), {})
            rows.append({**row, "name": meta.get("name"), "unit": meta.get("unit")})
        return _ok({"targets": rows})
    except Exception as e:
        return _err(e)


@mcp.tool(annotations=_WRITE)
def set_nutrient_target(
    nutrient: str,
    minimum: float | None = None,
    maximum: float | None = None,
    visible: bool | None = None,
) -> str:
    """Set a nutrient's daily target, its upper limit, or whether it is tracked.

    Giving a minimum or maximum makes it a custom target, replacing the default
    Cronometer works out from the profile. Setting visible turns tracking of
    that nutrient on or off, which is how a micronutrient starts showing up in
    the diary at all.

    Only what you pass changes: the rest of the nutrient's settings are read
    first and kept, so turning on visibility never disturbs an existing target.

    Going back to Cronometer's own default is done in the app, under Settings
    then Targets. Report the current value from get_targets before overwriting
    one, so it can be put back by hand if wanted.

    Args:
        nutrient: Nutrient name, e.g. "protein", "iodine", "choline", "biotin".
            Call list_nutrients for the accepted names.
        minimum: Daily target, in that nutrient's own unit.
        maximum: Upper limit, in that nutrient's own unit.
        visible: True to track the nutrient, False to hide it.
    """
    try:
        client = _get_client()
        if minimum is None and maximum is None and visible is None:
            return _err(ValueError("Give at least one of minimum, maximum or visible"))
        previous = None
        index = client.nutrient_index()
        entry = index.get(nutrient.strip().lower().replace(" ", "_"))
        if entry:
            previous = client.find_target(entry["id"])
        result = client.set_target(
            nutrient, minimum=minimum, maximum=maximum, visible=visible
        )
        return _ok({**result, "previous": previous})
    except Exception as e:
        return _err(e)


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------


def date_module_today() -> date:
    """Return today's date in the account's timezone.

    Uses the authenticated client's timezone (resolved from the Cronometer
    account) so response echoes match the diary day an entry actually lands
    on, independent of the host clock. Extracted for easy mocking in tests.
    """
    return _get_client().today()


# ------------------------------------------------------------------
# Entrypoint
# ------------------------------------------------------------------


def main():
    """Run the server on stdin/stdout, or over HTTP.

    Over HTTP it has no login of its own, so it only listens on the local
    machine and is only ever reached through auth-server.js.
    """
    import argparse

    # Load .env for local development (credentials). No-op if the file is
    # missing. override=False keeps real environment variables (systemd,
    # MCP client `env` blocks, etc.) authoritative over .env.
    from dotenv import find_dotenv, load_dotenv

    dotenv_path = find_dotenv(usecwd=True)
    if dotenv_path and load_dotenv(dotenv_path, override=False):
        logger.info("Loaded .env from %s", dotenv_path)

    parser = argparse.ArgumentParser(prog="cronometer-mcp")
    parser.add_argument(
        "--transport",
        choices=("stdio", "http"),
        default=os.getenv("MCP_TRANSPORT", "stdio"),
    )
    parser.add_argument("--host", default=os.getenv("MCP_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.getenv("MCP_PORT", "8430")))
    args = parser.parse_args()

    if args.transport == "stdio":
        mcp.run(transport="stdio")
        return

    if args.host not in ("127.0.0.1", "::1", "localhost"):
        raise SystemExit(
            f"refusing to listen on {args.host}: this server has no login of "
            "its own. Keep it on the local machine and put auth-server.js in "
            "front of it."
        )

    mcp.settings.host = args.host
    mcp.settings.port = args.port
    logger.info("Listening on http://%s:%d/mcp", args.host, args.port)
    mcp.run(transport="streamable-http")


if __name__ == "__main__":
    main()
