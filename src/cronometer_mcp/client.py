"""Client for the Cronometer API that the Android app uses.

Cronometer publishes no API, so this was worked out from the Android app
(v4.52.6) and talks to mobile.cronometer.com/api/v2/* with plain JSON.

The list of endpoints was read out of the app's compiled code. See the
calorie-estimator project for the traffic capture that first worked out how
logging in and the earliest endpoints work.
"""

import json
import logging
import math
import os
from datetime import date, datetime
from pathlib import Path
from typing import ClassVar
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import httpx

logger = logging.getLogger(__name__)

BASE_URL = "https://mobile.cronometer.com"

# Fallback timezone used only if the account's timezone can't be resolved from
# the login response. Matches the value historically assumed by this client.
_DEFAULT_TIMEZONE = "America/New_York"

# Optional deploy-time override for the account timezone. When set to a valid
# IANA zone name it is authoritative over both the login response and any
# cached value. This is the escape hatch for accounts whose server-side zone
# was clobbered by older builds (see issue #29) or when the resolved zone is
# otherwise wrong.
_ACCOUNT_TZ_ENV = "CRONOMETER_ACCOUNT_TZ"

# Cache the auth token across processes to avoid /api/v2/login rate limits.
# Cronometer throttles repeated logins per account; reusing a sessionKey lets
# short-lived CLI invocations behave like a long-running app.
_DEFAULT_SESSION_PATH = (
    Path(os.getenv("XDG_CACHE_HOME") or Path.home() / ".cache")
    / "cronometer-mcp"
    / "session.json"
)

# Auth block sent with every request (mimics the Android app)
_APP_AUTH_TEMPLATE = {
    "api": 3,
    "os": "Android",
    "build": "2807",
    "flavour": "free",
}

# Cronometer nutrient IDs (from the login response nutrient list)
NUTRIENT_IDS = {
    "energy": 208,
    "protein": 203,
    "fat": 204,
    "carbs": 205,
    "fiber": 291,
    "sugar": 269,
    "sodium": 307,
    "alcohol": 221,
    "net_carbs": -1205,
    "saturated_fat": 606,
    "cholesterol": 601,
    "trans_fat": 605,
    "omega_3": 10001,
    "omega_6": 10002,
}

# Macro fields surfaced as a flat convenience block in the daily summary,
# mapped to their nutrient IDs. These are the values most relevant when
# summarizing a day at a glance.
SUMMARY_MACRO_IDS = {
    "energy": 208,
    "protein": 203,
    "carbs": 205,
    "net_carbs": -1205,
    "fat": 204,
    "fiber": 291,
    "alcohol": 221,
}


# Nutrients Cronometer computes rather than stores. Sending one is rejected or
# silently overwritten, so they are filtered out of any write.
COMPUTED_NUTRIENT_IDS = frozenset({-203, -204, -205, -221, -1205})

# Spellings that are easier to type than the catalog's own names, or that the
# food label uses instead. Mapped to the canonical slug derived from the API.
NUTRIENT_ALIASES = {
    "calories": "energy",
    "kcal": "energy",
    "carbohydrates": "carbs",
    "saturated_fat": "saturated",
    "trans_fat": "trans_fats",
    "monounsaturated_fat": "monounsaturated",
    "polyunsaturated_fat": "polyunsaturated",
    "sugar": "sugars",
    "vitamin_b1": "b1_thiamine",
    "thiamine": "b1_thiamine",
    "vitamin_b2": "b2_riboflavin",
    "riboflavin": "b2_riboflavin",
    "vitamin_b3": "b3_niacin",
    "niacin": "b3_niacin",
    "vitamin_b5": "b5_pantothenic_acid",
    "pantothenic_acid": "b5_pantothenic_acid",
    "vitamin_b6": "b6_pyridoxine",
    "pyridoxine": "b6_pyridoxine",
    "vitamin_b12": "b12_cobalamin",
    "cobalamin": "b12_cobalamin",
    "lutein": "lutein_zeaxanthin",
    "zeaxanthin": "lutein_zeaxanthin",
}


def _round_sig(value: float, digits: int = 6) -> float:
    """Round to significant figures rather than decimal places.

    Summing per-entry amounts accumulates float error, so a round 100 mg arrives
    as 99.9997. A fixed number of decimals cannot fix that for both ends of the
    range at once: enough precision for a microgram of B12 leaves the milligram
    values ragged, and enough rounding to tidy those flattens the micrograms to
    zero.
    """
    if not value or not math.isfinite(value):
        return value
    return round(value, -math.floor(math.log10(abs(value))) + (digits - 1))


def _slug(name: str) -> str:
    """Turn a catalog nutrient name into a stable snake_case key.

    "B12 (Cobalamin)" -> "b12_cobalamin", "Lutein+Zeaxanthin" -> "lutein_zeaxanthin".
    """
    out = []
    for ch in name.lower():
        out.append(ch if ch.isalnum() else " ")
    return "_".join("".join(out).split())


class CronometerError(Exception):
    """Raised when a Cronometer API call fails."""


class CronometerClient:
    """Stateful client for the Cronometer mobile API.

    Caches the auth token in memory and reuses it across requests.
    Re-authenticates automatically when the session expires.
    """

    def __init__(self, *, session_path: Path | None = None) -> None:
        self._user_id: int | None = None
        self._token: str | None = None
        # IANA timezone name of the Cronometer account, resolved from the login
        # response (or a restored session cache). Diary timestamps and "today"
        # are computed in this zone so behavior is independent of the host clock.
        self._timezone: str | None = None
        self._session_path: Path = session_path or _DEFAULT_SESSION_PATH
        # Cache of nutrient definitions (id -> {name, unit, category}).
        # Definitions are stable for an account, so fetch them once.
        self._nutrient_defs: dict[int, dict] | None = None
        self._http = httpx.Client(
            base_url=BASE_URL,
            headers={
                "user-agent": "Dart/3.9 (dart:io)",
                "content-type": "text/plain; charset=utf-8",
                "accept-encoding": "gzip",
            },
            timeout=30.0,
        )
        self._load_cached_session()

    # ------------------------------------------------------------------
    # Authentication
    # ------------------------------------------------------------------

    def _cache_key(self) -> str:
        """Tie the cached session to the configured username so
        switching accounts invalidates the cache automatically."""
        return os.getenv("CRONOMETER_USERNAME", "")

    def _load_cached_session(self) -> None:
        """Restore (user_id, token, timezone) from disk if a cache file exists.

        Silently ignores any read/parse error: the worst case is we
        re-login, which is the original behaviour. A cache written by an
        older version that predates timezone persistence is treated as
        invalid so the next login refreshes the account timezone.
        """
        try:
            raw = self._session_path.read_text()
        except OSError:
            return
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return
        if data.get("username") != self._cache_key():
            return
        token = data.get("token")
        user_id = data.get("user_id")
        timezone = data.get("timezone")
        # Reject caches that lack a stored timezone (pre-timezone schema) so we
        # re-login once and pick up the account zone rather than guessing.
        if not isinstance(timezone, str):
            return
        if isinstance(token, str) and isinstance(user_id, int):
            self._user_id = user_id
            self._token = token
            # A CRONOMETER_ACCOUNT_TZ override wins over the cached value so a
            # session.json poisoned by an older build (issue #29) can't defeat
            # an explicit deploy-time setting without invalidating the cache.
            self._timezone = self._resolve_timezone(timezone)
            logger.debug(
                "Restored Cronometer session for user_id=%d (tz=%s) from %s",
                user_id,
                self._timezone,
                self._session_path,
            )

    def _save_cached_session(self) -> None:
        """Persist (user_id, token, timezone) so future processes can reuse it."""
        if self._user_id is None or self._token is None:
            return
        try:
            self._session_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._session_path.with_suffix(".json.tmp")
            tmp.write_text(
                json.dumps(
                    {
                        "username": self._cache_key(),
                        "user_id": self._user_id,
                        "token": self._token,
                        "timezone": self._timezone,
                    }
                )
            )
            os.replace(tmp, self._session_path)
            try:
                os.chmod(self._session_path, 0o600)
            except OSError:
                pass
        except OSError as exc:
            logger.warning("Failed to persist Cronometer session: %s", exc)

    def _invalidate_session(self) -> None:
        """Drop the in-memory token and remove the cache file."""
        self._token = None
        self._timezone = None
        try:
            self._session_path.unlink()
        except FileNotFoundError:
            pass
        except OSError as exc:
            logger.debug("Could not remove cached session: %s", exc)

    def _get_credentials(self) -> tuple[str, str]:
        username = os.getenv("CRONOMETER_USERNAME")
        password = os.getenv("CRONOMETER_PASSWORD")
        if not username or not password:
            raise CronometerError(
                "CRONOMETER_USERNAME and CRONOMETER_PASSWORD env vars must be set"
            )
        return username, password

    @staticmethod
    def _totp_code() -> str | None:
        """Current TOTP code, or None when the account has no 2FA.

        Cronometer rejects login with TOTP_CODE_REQUIRED when 2FA is on, so an
        unattended server needs the shared secret rather than a typed code.
        """
        secret = os.getenv("CRONOMETER_TOTP_SECRET")
        if not secret:
            return None
        try:
            import pyotp
        except ImportError as exc:
            raise CronometerError(
                "CRONOMETER_TOTP_SECRET is set but pyotp is not installed"
            ) from exc
        return pyotp.TOTP(secret.replace(" ", "")).now()

    def login(self) -> None:
        """Authenticate with Cronometer and cache the session token."""
        username, password = self._get_credentials()

        payload = {
            "email": username,
            "password": password,
            # Must stay null: the login endpoint treats a non-null timezone as
            # a *write* that overwrites the account's server-side zone (verified
            # against the live API — sending "Asia/Tokyo" changed the account
            # setting and it persisted across subsequent logins). Older builds
            # hardcoded "America/New_York" here, silently resetting every user's
            # account zone to Eastern on each login (issue #29). Sending null
            # leaves the account setting untouched and the response echoes the
            # account's real zone.
            "timezone": None,
            "userCode": self._totp_code(),
            "build": "4.48.2 b2807-a",
            "device": "Android 14 (SDK 34), Google Pixel 6 Pro",
            "firebaseToken": "",
            "features": {
                "food_search_config": '{"newSearch": true, "newSpellcheck": true}',
                "use_gpt_autofill": "true",
            },
            "auth": {
                "userId": None,
                "token": None,
                **_APP_AUTH_TEMPLATE,
            },
            "lastSeen": 0,
            "config": {"call_version": 2},
        }

        logger.info("Logging in to Cronometer as %s", username)
        resp = self._http.post("/api/v2/login", json=payload)
        resp.raise_for_status()
        data = resp.json()

        if data.get("result") != "SUCCESS" and "sessionKey" not in data:
            if data.get("error") == "TOTP_CODE_REQUIRED":
                raise CronometerError(
                    "Cronometer wants a 2FA code. Set CRONOMETER_TOTP_SECRET to "
                    "the base32 secret so the server can generate its own, or "
                    "turn 2FA off for this account."
                )
            raise CronometerError(f"Login failed: {data}")

        self._user_id = data["id"]
        self._token = data["sessionKey"]
        # The login response embeds the account profile, including the user's
        # configured IANA timezone. Prefer it over the host clock so diary
        # timestamps are correct regardless of where the server runs. A
        # CRONOMETER_ACCOUNT_TZ override, if set, wins over the response.
        self._timezone = self._resolve_timezone(data.get("timezone"))
        self._save_cached_session()
        logger.info(
            "Cronometer login successful (userId=%d, tz=%s, token=%s...)",
            self._user_id,
            self._timezone,
            self._token[:8] if self._token else "???",
        )

    def _ensure_auth(self) -> None:
        """Login lazily on first use."""
        if self._token is None:
            self.login()

    @property
    def user_id(self) -> int:
        """Authenticated user id; logs in first if needed (#30/#31)."""
        self._ensure_auth()
        assert self._user_id is not None
        return self._user_id

    def _auth_block(self) -> dict:
        return {
            "userId": self._user_id,
            "token": self._token,
            **_APP_AUTH_TEMPLATE,
        }

    # ------------------------------------------------------------------
    # Request helpers
    # ------------------------------------------------------------------

    def _request(self, endpoint: str, payload: dict, *, _retried: bool = False) -> dict:
        """Send a v2 POST request with JSON auth block. Re-authenticates once on failure.

        Callers must build payloads from authenticated state (read identity via
        self.user_id, not self._user_id) so the retry can safely re-send the dict.
        """
        self._ensure_auth()

        payload["auth"] = self._auth_block()
        payload.setdefault("lastSeen", 0)

        logger.debug("Cronometer v2 request: POST %s", endpoint)
        resp = self._http.post(endpoint, json=payload)

        # Check for auth-related failures and retry once
        if resp.status_code in (401, 403) and not _retried:
            logger.warning(
                "Cronometer auth rejected (%d), re-authenticating",
                resp.status_code,
            )
            self._invalidate_session()
            self.login()
            return self._request(endpoint, payload, _retried=True)

        resp.raise_for_status()
        data = resp.json()

        # Some endpoints return errors in the body with an HTTP 200. An expired
        # session comes back as {"result": "FAIL", "error": "..."}; "FAILURE" is
        # kept defensively (never observed in real traffic, but harmless).
        if isinstance(data, dict) and data.get("result") in ("FAIL", "FAILURE"):
            # Only an auth-shaped failure earns a re-login. Treating every FAIL
            # as an expired session turns a burst of validation errors (bad
            # parameter, unknown enum) into a login storm, and Cronometer
            # rate-limits logins hard enough that the storm locks the account
            # out for a while.
            error_text = str(data.get("error", "")).lower()
            auth_shaped = any(
                w in error_text for w in ("token", "session", "auth", "login")
            )
            if auth_shaped and not _retried:
                logger.warning("Cronometer session rejected, re-authenticating: %s", data)
                self._invalidate_session()
                self.login()
                return self._request(endpoint, payload, _retried=True)
            raise CronometerError(f"Cronometer API error: {data}")

        return data

    def _v3_headers(self) -> dict:
        """Headers for v3 REST API requests (auth via headers, not JSON body)."""
        return {
            "x-crono-session": self._token,
            "x-crono-app-os": "android",
            "x-crono-app-build-number": "2807",
            "x-crono-app-version": "4.48.2",
            "content-type": "application/json; charset=utf-8",
        }

    def _request_v3(
        self,
        method: str,
        path: str,
        *,
        json_body: dict | None = None,
        _retried: bool = False,
    ) -> httpx.Response:
        """Send a v3 REST API request. Auth is via x-crono-session header.

        The v3 API uses RESTful conventions: HTTP verbs, path-based routing,
        and standard status codes (e.g. 204 for successful deletes).

        Returns the raw httpx.Response (caller handles status interpretation).
        """
        self._ensure_auth()

        url = f"/api/v3/user/{self.user_id}{path}"
        logger.debug("Cronometer v3 request: %s %s", method, url)

        resp = self._http.request(
            method, url, json=json_body, headers=self._v3_headers()
        )

        # Re-authenticate once on auth failures
        if resp.status_code in (401, 403) and not _retried:
            logger.warning(
                "Cronometer v3 auth rejected (%d), re-authenticating",
                resp.status_code,
            )
            self._invalidate_session()
            self.login()
            return self._request_v3(method, path, json_body=json_body, _retried=True)

        return resp

    # ------------------------------------------------------------------
    # Date helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _env_timezone() -> str | None:
        """Return a valid IANA zone from CRONOMETER_ACCOUNT_TZ, or None.

        An invalid name is logged and ignored so a typo can't hard-fail
        startup; resolution then falls through to the response/cache value.
        """
        name = os.getenv(_ACCOUNT_TZ_ENV)
        if not name:
            return None
        try:
            ZoneInfo(name)
        except (ZoneInfoNotFoundError, ValueError):
            logger.warning(
                "Ignoring invalid %s=%r (not a known IANA timezone)",
                _ACCOUNT_TZ_ENV,
                name,
            )
            return None
        return name

    def _resolve_timezone(self, response_tz: str | None) -> str:
        """Resolve the account timezone by priority.

        1. CRONOMETER_ACCOUNT_TZ env override (authoritative escape hatch).
        2. The value from the login response (trustworthy now that login()
           no longer overwrites the account's server-side zone; see #29).
        3. The historical default.
        """
        env = self._env_timezone()
        if env:
            return env
        if isinstance(response_tz, str) and response_tz:
            return response_tz
        return _DEFAULT_TIMEZONE

    def _tzinfo(self) -> ZoneInfo:
        """Return the account's timezone, falling back to the default.

        Resolved from the login response (or restored session cache). If the
        stored name is unset or unknown (e.g. a zone missing from the system
        tzdata), log once and fall back so stamping never hard-fails.
        """
        name = self._timezone or _DEFAULT_TIMEZONE
        try:
            return ZoneInfo(name)
        except (ZoneInfoNotFoundError, ValueError):
            logger.warning(
                "Unknown account timezone %r; falling back to %s",
                name,
                _DEFAULT_TIMEZONE,
            )
            return ZoneInfo(_DEFAULT_TIMEZONE)

    def now(self) -> datetime:
        """Current wall-clock time in the account's timezone (aware)."""
        return datetime.now(self._tzinfo())

    def today(self) -> date:
        """Today's date in the account's timezone."""
        return self.now().date()

    def _format_day(self, d: date | None = None) -> str:
        """Format a date as Cronometer expects: non-zero-padded 'YYYY-M-D'.

        Defaults to today in the account's timezone, not the host clock.
        """
        d = d or self.today()
        return f"{d.year}-{d.month}-{d.day}"

    # ------------------------------------------------------------------
    # Food search
    # ------------------------------------------------------------------

    def search_food(self, query: str) -> list[dict]:
        """Search the Cronometer food database.

        Returns a list of food entries, each with keys:
        id, name, measureId, translationId, measureDisplayName, source,
        globalPopularity, score, etc.
        """
        payload = {
            "query": query,
            "tab": "ALL",
            "sources": ["All"],
            "config": {
                "newSearch": True,
                "newSpellcheck": True,
                "call_version": 1,
            },
        }
        data = self._request("/api/v2/find_food", payload)
        foods = data.get("foods", [])
        logger.info("Food search for %r returned %d results", query, len(foods))
        return foods

    # ------------------------------------------------------------------
    # Food details
    # ------------------------------------------------------------------

    def get_food(self, food_id: int) -> dict:
        """Fetch full food details, including server-assigned measure IDs.

        Returns the full food object with keys: id, name, measures,
        defaultMeasureId, nutrients, etc.
        """
        payload = {"id": food_id, "config": {"call_version": 1}}
        data = self._request("/api/v2/get_food", payload)
        logger.info(
            "Fetched food %d: %r (defaultMeasureId=%s)",
            food_id,
            data.get("name"),
            data.get("defaultMeasureId"),
        )
        return data

    def get_foods(self, food_ids: list[int]) -> list[dict]:
        """Batch-fetch full food details for many food IDs in one call.

        Mirrors get_food but resolves a list of IDs at once, which is how the
        Cronometer app resolves an entire day's diary. Returns a list of food
        objects, each with keys: id, name, source, measures, defaultMeasureId,
        nutrients, etc. Nutrient amounts are stored per-100g.

        Returns an empty list if food_ids is empty.
        """
        if not food_ids:
            return []
        payload = {"ids": list(food_ids), "config": {"call_version": 1}}
        data = self._request("/api/v2/get_foods", payload)
        foods = data.get("foods", []) if isinstance(data, dict) else []
        logger.info("Batch-fetched %d/%d foods", len(foods), len(food_ids))
        return foods

    # ------------------------------------------------------------------
    # Custom food creation
    # ------------------------------------------------------------------

    def create_custom_food(
        self,
        name: str,
        nutrients: dict[str, float],
        *,
        serving_name: str = "1 serving",
        serving_grams: float = 100.0,
        label_type: str = "AMERICAN_2016",
        notes: str | None = None,
        category: int = 0,
    ) -> dict:
        """Create a custom food carrying any subset of the nutrient catalog.

        `nutrients` maps nutrient names to amounts for one whole serving, in
        each nutrient's own catalog unit (see nutrient_index). Amounts are
        converted to per-100g here because that is how Cronometer stores them.

        Two conveniences the food label has but the catalog does not:
        `energy_kj` is converted to kcal, and `salt_g` to sodium in mg. Passing
        both a convenience and its underlying nutrient is an error rather than a
        silent pick, since the two would disagree.

        Returns {"food_id": int, "measure_id": int | None}.
        """
        values = dict(nutrients)

        energy_kj = values.pop("energy_kj", None)
        if energy_kj is not None:
            if "energy" in values or "calories" in values:
                raise CronometerError("Pass either energy_kj or energy, not both")
            values["energy"] = float(energy_kj) / 4.184

        salt_g = values.pop("salt_g", None)
        if salt_g is not None:
            if "sodium" in values:
                raise CronometerError("Pass either salt_g or sodium, not both")
            # Salt is 39.34% sodium by mass (Na 22.99 of NaCl 58.44).
            values["sodium"] = float(salt_g) * 393.4

        resolved = self.resolve_nutrients(values)
        if not resolved:
            raise CronometerError("A custom food needs at least one nutrient")

        # Cronometer stores nutrients per 100g - normalize from per-serving.
        scale = 100.0 / serving_grams if serving_grams > 0 else 1.0
        for entry in resolved:
            entry["amount"] = round(entry["amount"] * scale, 4)

        payload = {
            "data": {
                "id": 0,
                "name": name,
                "category": category,
                "owner": None,
                "retired": None,
                "source": None,
                "defaultMeasureId": 0,
                "comments": notes,
                "alternateId": None,
                "measures": [
                    {
                        "id": 0,
                        "name": serving_name,
                        "value": serving_grams,
                        "amount": 1.0,
                        "type": "Atomic",
                    }
                ],
                "labelType": label_type,
                "nutrients": resolved,
                "properties": {},
                "foodTags": [],
            },
            "config": {"call_version": 1},
        }

        data = self._request("/api/v2/add_food", payload)
        food_id = data.get("id")
        if not food_id:
            raise CronometerError(f"Failed to create custom food: {data}")

        logger.info("Created custom food %r (id=%d)", name, food_id)
        return {"food_id": food_id, "measure_id": None}

    def get_recent_foods(self) -> list[dict]:
        """Recently logged foods with how often each was logged.

        Uses: POST /api/v2/get_recent_foods
        """
        data = self._request("/api/v2/get_recent_foods", {})
        out = []
        for row in data.get("servings", []):
            food = row.get("food") or {}
            out.append(
                {
                    "food_id": food.get("id"),
                    "name": food.get("name"),
                    "times_logged": row.get("count"),
                    "default_measure_id": food.get("defaultMeasureId"),
                    "is_recipe": bool(food.get("meal")),
                }
            )
        logger.info("Fetched %d recent foods", len(out))
        return out

    def get_streak(self, day: date | None = None) -> dict:
        """Diary logging streaks as of a day.

        Uses: POST /api/v2/get_streak
        """
        data = self._request("/api/v2/get_streak", {"day": self._format_day(day)})
        logger.info("Fetched streaks")
        return data

    def get_profile(self) -> dict:
        """The account profile: birthdate, gender, timezone, language.

        Uses: POST /api/v2/get_profile
        """
        data = self._request("/api/v2/get_profile", {})
        logger.info("Fetched profile")
        return data

    def create_recipe(
        self,
        name: str,
        ingredients: list[dict],
        *,
        servings: float = 1.0,
        notes: str | None = None,
        recipe_id: int = 0,
    ) -> dict:
        """Create a recipe: a food whose nutrients come from its ingredients.

        Each ingredient is {"food_id": int, "grams": float, "measure_id": int
        (optional)}. Nutrients are not sent - Cronometer sums them from the
        ingredients itself, which is the whole point of a recipe over a custom
        food. `servings` says how many portions the batch makes, and becomes a
        "serving" measure of total_grams/servings so one portion can be logged
        directly.

        Passing recipe_id updates that recipe in place instead of creating one,
        replacing its ingredient list.

        Uses: POST /api/v2/add_food with meal=true
        """
        if not ingredients:
            raise CronometerError("A recipe needs at least one ingredient")
        rows = []
        total_grams = 0.0
        for ing in ingredients:
            food_id = ing.get("food_id") or ing.get("foodId")
            grams = ing.get("grams")
            if not food_id or not grams:
                raise CronometerError(
                    "Each ingredient needs food_id and grams, got: " f"{ing}"
                )
            rows.append(
                {
                    "foodId": int(food_id),
                    "measureId": int(ing.get("measure_id") or ing.get("measureId") or 0),
                    "grams": float(grams),
                    "amount": 1.0,
                }
            )
            total_grams += float(grams)

        if servings <= 0:
            raise CronometerError("servings must be positive")
        per_serving = round(total_grams / servings, 1)

        payload = {
            "data": {
                "id": recipe_id,
                "name": name,
                "category": 0,
                "owner": None,
                "retired": None,
                "source": None,
                "defaultMeasureId": 0,
                "comments": notes,
                "alternateId": None,
                "measures": [
                    {
                        "id": 0,
                        "name": "serving",
                        "value": per_serving,
                        "amount": 1.0,
                        "type": "Atomic",
                    }
                ],
                "labelType": "AMERICAN_2016",
                "nutrients": [],
                "properties": {},
                "foodTags": [],
                "meal": True,
                "ingredients": rows,
            },
            "config": {"call_version": 1},
        }
        data = self._request("/api/v2/add_food", payload)
        food_id = data.get("id")
        if not food_id:
            raise CronometerError(f"Failed to create recipe: {data}")
        logger.info(
            "Created recipe %r (id=%d, %d ingredients, %.0fg, %s servings)",
            name, food_id, len(rows), total_grams, servings,
        )
        return {
            "food_id": food_id,
            "total_grams": total_grams,
            "grams_per_serving": per_serving,
        }

    def retire_custom_food(self, food_id: int, retired: bool = True) -> dict:
        """Retire a custom food, which is how Cronometer removes one.

        There is no delete endpoint for foods. Re-sending the food with its
        `retired` flag set is what the app does: the food stops being offered
        for new entries, and diary entries already referencing it keep working.
        Pass retired=False to bring one back.
        """
        food = self.get_food(food_id)
        food["retired"] = retired
        data = self._request(
            "/api/v2/add_food", {"data": food, "config": {"call_version": 1}}
        )
        logger.info("Set retired=%s on food %s", retired, food_id)
        return data

    # ------------------------------------------------------------------
    # Diary: add serving
    # ------------------------------------------------------------------

    def add_serving(
        self,
        food_id: int,
        measure_id: int | None,
        grams: float,
        translation_id: int = 0,
        day: date | None = None,
        diary_group: int = 0,
    ) -> dict:
        """Log a food serving to the diary.

        Args:
            food_id: Cronometer food ID.
            measure_id: Measure/unit ID. Get this from search_food() results
                        (measureId field) or get_food() (defaultMeasureId or measures[].id).
                        0 is only valid for user-created custom foods; database-sourced
                        foods (CRDB/NCCDB/FDC) require a real measure ID.
            grams: Weight in grams.
            translation_id: Translation ID (from search results, usually 0).
            day: Date to log to. Defaults to today.
            diary_group: Meal group. 0 = auto (based on time of day),
                         1 = Breakfast, 2 = Lunch, 3 = Dinner, 4 = Snacks.

        Returns the serving confirmation dict from the API.
        """
        now = self.now()
        day_str = self._format_day(day)
        time_str = f"{now.hour}:{now.minute}:{now.second}"

        if diary_group == 0:
            diary_group = _meal_group_for_hour(now.hour)

        serving = {
            "order": (diary_group << 16) | 1,
            "day": day_str,
            "time": time_str,
            "offset": None,
            "source": None,
            "userId": self.user_id,
            "servingId": None,
            "type": "Serving",
            "foodId": food_id,
            "measureId": measure_id or 0,
            "grams": grams,
            "translationId": translation_id,
        }

        payload = {
            "serving": serving,
            "config": {"call_version": 2},
        }

        data = self._request("/api/v2/add_serving", payload)
        logger.info(
            "Logged serving: food_id=%d, grams=%.1f, day=%s (serving_id=%s)",
            food_id,
            grams,
            day_str,
            data.get("id"),
        )
        return data

    # ------------------------------------------------------------------
    # Diary: get diary entries
    # ------------------------------------------------------------------

    def get_diary(self, day: date | None = None) -> dict:
        """Get all diary entries for a given day.

        Args:
            day: Date to fetch. Defaults to today.

        Returns the full diary response from the API.
        """
        payload = {
            "day": self._format_day(day),
            "config": {"call_version": 1},
        }
        data = self._request("/api/v2/get_diary", payload)
        logger.info("Fetched diary for %s", self._format_day(day))
        return data

    # ------------------------------------------------------------------
    # Diary: delete entries
    # ------------------------------------------------------------------

    def delete_entries(self, entry_ids: list[str], day: date | None = None) -> dict:
        """Remove diary entries by their serving IDs.

        Fetches the diary for the given day, matches entries by servingId,
        and sends the full serving objects to the v3 DELETE endpoint.

        Uses: DELETE /api/v3/user/{userId}/diary-entries

        Args:
            entry_ids: List of serving IDs to delete (as strings).
            day: The day the entries belong to. Defaults to today.

        Returns dict with removed IDs and count.
        """
        # Fetch the diary to get full serving objects (required by v3 API)
        diary_data = self.get_diary(day)
        diary_entries = diary_data.get("diary", [])

        id_set = {str(eid) for eid in entry_ids}
        to_delete = []
        for entry in diary_entries:
            if str(entry.get("servingId")) in id_set:
                to_delete.append(entry)

        if not to_delete:
            logger.warning(
                "None of the requested entry IDs found in diary for %s",
                self._format_day(day),
            )
            return {"removed": [], "count": 0}

        resp = self._request_v3(
            "DELETE",
            "/diary-entries",
            json_body={"diaryEntries": to_delete},
        )

        if resp.status_code == 204:
            removed_ids = [str(e["servingId"]) for e in to_delete]
            logger.info(
                "Deleted %d entries for %s: %s",
                len(removed_ids),
                self._format_day(day),
                removed_ids,
            )
            return {"removed": removed_ids, "count": len(removed_ids)}
        else:
            raise CronometerError(
                f"Delete failed with status {resp.status_code}: {resp.text[:300]}"
            )

    # ------------------------------------------------------------------
    # Diary: mark day complete
    # ------------------------------------------------------------------

    def mark_day_complete(self, day: date | None = None, complete: bool = True) -> dict:
        """Mark a diary day as complete or incomplete.

        Args:
            day: Date to mark. Defaults to today.
            complete: True to mark complete, False for incomplete.

        Returns the API response.
        """
        payload = {
            "day": self._format_day(day),
            "complete": complete,
            "config": {"call_version": 1},
        }
        data = self._request("/api/v2/set_complete", payload)
        status = "complete" if complete else "incomplete"
        logger.info("Marked %s as %s", self._format_day(day), status)
        return data

    # ------------------------------------------------------------------
    # Diary: copy from yesterday
    # ------------------------------------------------------------------

    def copy_day(
        self, from_day: date | None = None, to_day: date | None = None
    ) -> dict:
        """Copy all diary entries from one day to another.

        Uses: POST /api/v2/copy

        Args:
            from_day: Source date. Defaults to yesterday.
            to_day: Destination date. Defaults to today.

        Returns the API response with the copied entries.
        """
        from datetime import timedelta

        to_day = to_day or self.today()
        from_day = from_day or (to_day - timedelta(days=1))

        payload = {
            "from": self._format_day(from_day),
            "to": self._format_day(to_day),
            "diaryGroupNumber": None,
            "config": {"call_version": 1},
        }
        data = self._request("/api/v2/copy", payload)
        logger.info(
            "Copied entries from %s to %s",
            self._format_day(from_day),
            self._format_day(to_day),
        )
        return data

    # ------------------------------------------------------------------
    # Nutrition: get nutrients
    # ------------------------------------------------------------------

    def get_nutrients(self, day: date | None = None) -> dict:
        """Get nutrient totals for a given day.

        Args:
            day: Date to fetch. Defaults to today.

        Returns the nutrient summary from the API.
        """
        payload = {
            "day": self._format_day(day),
            "config": {"call_version": 1},
        }
        data = self._request("/api/v2/get_nutrients", payload)
        logger.info("Fetched nutrients for %s", self._format_day(day))
        return data

    def get_nutrition_scores(
        self, day: date | None = None, *, include_supplements: bool = True
    ) -> dict:
        """Get nutrition scores with per-nutrient consumed amounts.

        This is the richest nutrition endpoint -- it returns category scores
        (All Targets, Vitamins, Minerals, Electrolytes, Antioxidants, Immune
        Support, Metabolism, Bone Health, etc.) with the actual consumed amount
        and confidence level for each nutrient.

        Automatically fetches the diary to obtain serving IDs.

        Uses: POST /api/v2/get_nutrition_scores

        Args:
            day: Date to score. Defaults to today.
            include_supplements: Whether to include supplements in scoring.

        Returns the nutrition scores from the API.
        """
        diary_data = self.get_diary(day)
        diary_entries = diary_data.get("diary", [])

        serving_ids = [
            e["servingId"]
            for e in diary_entries
            if e.get("type") == "Serving" and "servingId" in e
        ]

        payload = {
            "startDay": "1900-1-1",
            "endDay": "1900-1-1",
            "servingIds": serving_ids,
            "supplements": "true" if include_supplements else "false",
            "config": {"call_version": 1},
        }
        data = self._request("/api/v2/get_nutrition_scores", payload)
        logger.info(
            "Fetched nutrition scores for %s (%d servings)",
            self._format_day(day),
            len(serving_ids),
        )
        return data

    def get_nutrient_definitions(self) -> dict[int, dict]:
        """Get the nutrient definition map (id -> {name, unit, category}).

        The get_nutrients endpoint returns the account's nutrient catalog --
        names, units, RDIs, and categories -- not consumed amounts. We use it
        purely to label nutrient IDs. Cached after the first call since the
        catalog is stable.
        """
        if self._nutrient_defs is None:
            data = self.get_nutrients()
            defs: dict[int, dict] = {}
            for n in data.get("nutrients", []):
                nid = n.get("id")
                if nid is None:
                    continue
                defs[nid] = {
                    "name": n.get("name"),
                    "unit": n.get("unit"),
                    "category": n.get("category"),
                }
            self._nutrient_defs = defs
        return self._nutrient_defs

    def nutrient_index(self) -> dict[str, dict]:
        """Writable nutrients keyed by a stable snake_case name.

        Built from the account's own catalog rather than a hardcoded table, so
        a nutrient Cronometer adds later needs no change here. Computed fields
        are excluded: they are derived from the others and cannot be set.
        """
        index: dict[str, dict] = {}
        for nid, meta in self.get_nutrient_definitions().items():
            if nid in COMPUTED_NUTRIENT_IDS or nid < 0 or not meta.get("name"):
                continue
            index[_slug(meta["name"])] = {
                "id": nid,
                "name": meta["name"],
                "unit": meta.get("unit"),
                "category": meta.get("category"),
            }
        return index

    def resolve_nutrients(self, values: dict[str, float]) -> list[dict]:
        """Map user-supplied nutrient names to the catalog's ids.

        Unknown names raise rather than being dropped: silently ignoring a
        misspelled nutrient would store a food that looks complete and is not.
        Only the names given are returned, so an unset nutrient stays unset
        rather than being written as a zero, which Cronometer treats as the
        active claim that the food contains none of it.
        """
        index = self.nutrient_index()
        resolved: list[dict] = []
        unknown: list[str] = []

        for raw_key, amount in values.items():
            if amount is None:
                continue
            key = _slug(str(raw_key))
            key = NUTRIENT_ALIASES.get(key, key)
            entry = index.get(key)
            if entry is None:
                unknown.append(raw_key)
                continue
            resolved.append({"id": entry["id"], "amount": float(amount)})

        if unknown:
            raise CronometerError(
                f"Unknown nutrient(s): {', '.join(sorted(unknown))}. "
                "Call list_nutrients for the accepted names."
            )
        return resolved

    def get_consumed_nutrients(
        self, day: date | None = None, *, include_untracked: bool = True
    ) -> dict:
        """Get consumed nutrient totals for a day, labeled and summarized.

        Tracked nutrients come from the server-computed totals in
        get_nutrition_scores ("All Targets"), so they match what the app shows.

        Cronometer only scores what has a target, so that source silently omits
        everything else: with no caffeine target set, a day's coffee reports no
        caffeine at all, and a consumer cannot tell that from a genuine zero.
        With include_untracked the remaining nutrients are summed from the
        diary's own per-entry amounts instead, which reproduce the server totals
        to within rounding. Each nutrient carries `tracked` so a value with a
        target is never confused with one that is informational only.

        Returns a dict:
            {
                "macros": {energy, protein, carbs, net_carbs, fat, fiber,
                           alcohol},  # flat amounts (None if absent that day)
                "nutrients": [
                    {id, name, amount, unit, category, confidence, tracked}, ...
                ],
                "tracked_count": int,
                "untracked_count": int,
            }
        """
        scores = self.get_nutrition_scores(day)

        # The "All Targets" category contains every tracked nutrient.
        all_targets = next(
            (c for c in scores.get("scores", []) if c.get("title") == "All Targets"),
            None,
        )
        components = (all_targets or {}).get("components", []) if all_targets else []

        defs = self.get_nutrient_definitions()

        nutrients: list[dict] = []
        amounts_by_id: dict[int, float] = {}
        for comp in components:
            nid = comp.get("nutrientId")
            if nid is None:
                continue
            amount = comp.get("amount")
            amounts_by_id[nid] = amount
            meta = defs.get(nid, {})
            nutrients.append(
                {
                    "id": nid,
                    "name": meta.get("name"),
                    "amount": amount,
                    "unit": meta.get("unit"),
                    "category": meta.get("category"),
                    "confidence": comp.get("confidence"),
                    "tracked": True,
                }
            )

        tracked_count = len(nutrients)

        if include_untracked:
            totals: dict[int, float] = {}
            diary = self.enrich_diary_servings(self.get_diary(day))
            for entry in diary.get("diary", []):
                for item in entry.get("nutrients") or []:
                    nid, amount = item.get("id"), item.get("amount")
                    if nid is None or amount is None or nid in amounts_by_id:
                        continue
                    totals[nid] = totals.get(nid, 0.0) + amount
            for nid, amount in sorted(totals.items()):
                meta = defs.get(nid, {})
                nutrients.append(
                    {
                        "id": nid,
                        "name": meta.get("name"),
                        "amount": _round_sig(amount),
                        "unit": meta.get("unit"),
                        "category": meta.get("category"),
                        "confidence": None,
                        "tracked": False,
                    }
                )
                amounts_by_id[nid] = amount

        macros = {key: amounts_by_id.get(nid) for key, nid in SUMMARY_MACRO_IDS.items()}

        logger.info(
            "Built consumed nutrient summary for %s (%d tracked, %d untracked)",
            self._format_day(day),
            tracked_count,
            len(nutrients) - tracked_count,
        )
        return {
            "macros": macros,
            "nutrients": nutrients,
            "tracked_count": tracked_count,
            "untracked_count": len(nutrients) - tracked_count,
        }

    def enrich_diary_servings(self, diary: dict) -> dict:
        """Merge food metadata into a raw get_diary payload (best-effort).

        Diary "Serving" entries carry only numeric IDs (foodId, measureId,
        grams). This resolves each foodId via a single batch get_foods call and
        merges per-entry:

          - name, source, category: from the food object
          - measure: {measure_id, name, grams_per_unit} for the entry's
            measureId (falls back to the food's defaultMeasureId)
          - servings: grams / grams_per_unit, when derivable
          - nutrients: the food's nutrient profile scaled to the entry's amount
            (per-100g for Weight/Atomic measures, per-serving for Recipe
            measures), labeled with name/unit/category via the nutrient
            definitions catalog

        Enrichment is best-effort: if the get_foods call fails or a food is not
        returned, the corresponding entries are left unchanged. The diary dict
        is mutated in place and also returned. Non-Serving entries (Exercise,
        Biometric) already carry a name and are left untouched.
        """
        if not isinstance(diary, dict):
            return diary
        entries = diary.get("diary")
        if not isinstance(entries, list):
            return diary

        food_ids = sorted(
            {
                e["foodId"]
                for e in entries
                if isinstance(e, dict)
                and e.get("type") == "Serving"
                and isinstance(e.get("foodId"), int)
            }
        )
        if not food_ids:
            return diary

        try:
            foods = self.get_foods(food_ids)
        except Exception as exc:  # best-effort: keep diary without names
            logger.warning("Diary enrichment skipped (get_foods failed): %s", exc)
            return diary

        food_by_id = {f.get("id"): f for f in foods if isinstance(f, dict)}
        try:
            defs = self.get_nutrient_definitions()
        except Exception:
            defs = {}

        for entry in entries:
            if not isinstance(entry, dict) or entry.get("type") != "Serving":
                continue
            food = food_by_id.get(entry.get("foodId"))
            if not food:
                continue

            entry["name"] = food.get("name")
            entry["source"] = food.get("source")
            if food.get("category") is not None:
                entry["category"] = food.get("category")

            measures = {
                m.get("id"): m for m in food.get("measures", []) if isinstance(m, dict)
            }
            measure = measures.get(entry.get("measureId")) or measures.get(
                food.get("defaultMeasureId")
            )
            grams = entry.get("grams")
            if measure:
                grams_per_unit = measure.get("value")
                entry["measure"] = {
                    "measure_id": measure.get("id"),
                    "name": measure.get("name"),
                    "grams_per_unit": grams_per_unit,
                }
                if (
                    isinstance(grams, (int, float))
                    and isinstance(grams_per_unit, (int, float))
                    and grams_per_unit
                ):
                    entry["servings"] = round(grams / grams_per_unit, 4)

            # Nutrient scaling depends on the measure type:
            #   - Recipe measures: nutrients are stored per one reference
            #     serving and the diary "grams" field is a serving count, so
            #     scale by grams directly.
            #   - Weight/Atomic measures: nutrients are stored per-100g and
            #     "grams" is real grams, so scale by grams / 100.
            if isinstance(grams, (int, float)):
                if measure and measure.get("type") == "Recipe":
                    scale = grams
                else:
                    scale = grams / 100.0
                scaled: list[dict] = []
                for n in food.get("nutrients", []):
                    if not isinstance(n, dict):
                        continue
                    nid = n.get("id")
                    amount = n.get("amount")
                    if nid is None or not isinstance(amount, (int, float)):
                        continue
                    meta = defs.get(nid, {})
                    scaled.append(
                        {
                            "id": nid,
                            "name": meta.get("name"),
                            "amount": round(amount * scale, 4),
                            "unit": meta.get("unit"),
                            "category": meta.get("category"),
                        }
                    )
                entry["nutrients"] = scaled

        logger.info("Enriched %d diary foods with names/nutrients", len(food_by_id))
        return diary

    # ------------------------------------------------------------------
    # Macro targets
    # ------------------------------------------------------------------

    def get_macro_schedules(self) -> dict:
        """Get the weekly macro target schedule.

        Returns the schedule mapping days of week to macro templates.
        """
        payload = {"config": {"call_version": 1}}
        data = self._request("/api/v2/get_macro_schedules", payload)
        logger.info("Fetched macro schedules")
        return data

    def get_macro_target_templates(self) -> dict:
        """Get all saved macro target templates.

        Returns the list of macro target templates with their values.
        """
        payload = {"config": {"call_version": 1}}
        data = self._request("/api/v2/get_macro_target_templates", payload)
        logger.info("Fetched macro target templates")
        return data

    # ------------------------------------------------------------------
    # Fasting
    # ------------------------------------------------------------------

    def get_fasting_with_date_range(
        self, start: date | None = None, end: date | None = None
    ) -> dict:
        """Get fasting history for a date range.

        Args:
            start: Start date. Defaults to 30 days ago.
            end: End date. Defaults to today.

        Returns fasting entries from the API.
        """
        from datetime import timedelta

        end = end or self.today()
        start = start or (end - timedelta(days=30))

        payload = {
            "start": self._format_day(start),
            "end": self._format_day(end),
            "config": {"call_version": 1},
        }
        data = self._request("/api/v2/get_fasting_with_date_range", payload)
        logger.info("Fetched fasting data %s to %s", start, end)
        return data

    def get_fasting_stats(self) -> dict:
        """Get aggregate fasting statistics.

        Returns total fasting hours, longest fast, averages, etc.
        """
        payload = {"config": {"call_version": 1}}
        data = self._request("/api/v2/get_fasting_stats", payload)
        logger.info("Fetched fasting stats")
        return data

    # ------------------------------------------------------------------
    # Biometrics
    # ------------------------------------------------------------------

    def get_metrics(self) -> list[dict]:
        """Get the biometric metric catalog.

        Each metric describes one trackable biometric (Weight, Body Fat,
        Heart Rate, Blood Glucose, Waist Size, ...) with keys: id, name,
        legacy (bool), and units -- a list of {id, name, ...} the value can
        be expressed in. Cronometer stores every biometric under one of
        these metric IDs.

        Uses: POST /api/v2/get_metrics
        """
        payload = {"config": {"call_version": 1}}
        data = self._request("/api/v2/get_metrics", payload)
        return data.get("metrics", [])

    def get_biometrics(
        self,
        metric_id: int,
        unit_id: int,
        start: date | None = None,
        end: date | None = None,
    ) -> dict:
        """Get a biometric time series (e.g. weight, body fat) over a range.

        Args:
            metric_id: Metric ID from get_metrics (e.g. 1 for Weight).
            unit_id: Unit ID from the metric's units list (e.g. 1 for kg).
            start: Start date. Defaults to 30 days before `end`.
            end: End date. Defaults to today.

        Uses: POST /api/v2/get_biometrics

        Returns the API response: {"data": [{"day": "YYYY-MM-DD", "value": float}, ...]}.
        """
        from datetime import timedelta

        end = end or self.today()
        start = start or (end - timedelta(days=30))

        payload = {
            "metricId": metric_id,
            "unitId": unit_id,
            "start": self._format_day(start),
            "end": self._format_day(end),
            "config": {"call_version": 1},
        }
        data = self._request("/api/v2/get_biometrics", payload)
        logger.info(
            "Fetched biometrics for metric %d (unit %d) %s to %s",
            metric_id,
            unit_id,
            self._format_day(start),
            self._format_day(end),
        )
        return data

    # ------------------------------------------------------------------
    # Diary: entry lookup
    # ------------------------------------------------------------------

    # The v2 write endpoints all take a whole entry object rather than a patch,
    # so an edit means read-modify-write against the day the entry lives on.
    _ID_FIELD: ClassVar[dict[str, str]] = {
        "Serving": "servingId",
        "Note": "noteId",
        "Biometric": "biometricId",
        "Exercise": "exerciseId",
    }

    def find_entry(self, entry_id: int, entry_type: str, day: date | None = None) -> dict:
        """Return a diary entry of the given type by its numeric id.

        Args:
            entry_id: The type's own id (servingId, noteId, biometricId, ...).
            entry_type: One of Serving, Note, Biometric, Exercise.
            day: Day the entry is on. Defaults to today.
        """
        id_field = self._ID_FIELD.get(entry_type)
        if id_field is None:
            raise CronometerError(f"Unknown diary entry type: {entry_type}")
        for entry in self.get_diary(day).get("diary", []):
            if entry.get("type") == entry_type and entry.get(id_field) == entry_id:
                return entry
        raise CronometerError(
            f"No {entry_type} with id {entry_id} in the diary for "
            f"{self._format_day(day)}"
        )

    # ------------------------------------------------------------------
    # Diary: servings
    # ------------------------------------------------------------------

    def edit_serving(
        self,
        serving_id: int,
        *,
        grams: float | None = None,
        time: str | None = None,
        day: date | None = None,
    ) -> dict:
        """Change the amount or time of a logged serving.

        Uses: POST /api/v2/edit_serving
        """
        serving = self.find_entry(serving_id, "Serving", day)
        if grams is not None:
            serving["grams"] = grams
        if time is not None:
            serving["time"] = time
        data = self._request("/api/v2/edit_serving", {"serving": serving})
        logger.info("Edited serving %s", serving_id)
        return data

    # ------------------------------------------------------------------
    # Diary: notes
    # ------------------------------------------------------------------

    def add_note(self, text: str, day: date | None = None) -> dict:
        """Add a diary note.

        Uses: POST /api/v2/add_note
        """
        note = {
            "type": "Note",
            "userId": self.user_id,
            "day": self._format_day(day),
            "text": text,
            "order": 0,
            "meta": {},
        }
        data = self._request("/api/v2/add_note", {"note": note})
        logger.info("Added note to %s", self._format_day(day))
        return data

    def edit_note(self, note_id: int, text: str, day: date | None = None) -> dict:
        """Replace the text of an existing diary note.

        Uses: POST /api/v2/edit_note
        """
        note = self.find_entry(note_id, "Note", day)
        note["text"] = text
        data = self._request("/api/v2/edit_note", {"note": note})
        logger.info("Edited note %s", note_id)
        return data

    # ------------------------------------------------------------------
    # Diary: biometrics
    # ------------------------------------------------------------------

    def add_biometric(
        self,
        metric_id: int,
        unit_id: int,
        amount: float,
        day: date | None = None,
    ) -> dict:
        """Record a biometric measurement.

        Uses: POST /api/v2/add_biometric
        """
        biometric = {
            "type": "Biometric",
            "userId": self.user_id,
            "day": self._format_day(day),
            "metricId": metric_id,
            "unitId": unit_id,
            "amount": amount,
            "order": 0,
            "meta": {},
        }
        data = self._request("/api/v2/add_biometric", {"biometric": biometric})
        logger.info("Added biometric metric=%d amount=%s", metric_id, amount)
        return data

    def edit_biometric(
        self, biometric_id: int, amount: float, day: date | None = None
    ) -> dict:
        """Change the value of a recorded biometric.

        Uses: POST /api/v2/edit_biometric
        """
        biometric = self.find_entry(biometric_id, "Biometric", day)
        biometric["amount"] = amount
        data = self._request("/api/v2/edit_biometric", {"biometric": biometric})
        logger.info("Edited biometric %s to %s", biometric_id, amount)
        return data

    # ------------------------------------------------------------------
    # Diary: exercise
    # ------------------------------------------------------------------

    def add_exercise(
        self,
        name: str,
        minutes: int,
        calories_burned: float,
        day: date | None = None,
    ) -> dict:
        """Log an exercise entry.

        Cronometer stores burned calories as a negative number; a positive
        value is accepted here and negated, since "burned 300" is how it reads
        everywhere else.

        Uses: POST /api/v2/add_exercise
        """
        exercise = {
            "type": "Exercise",
            "userId": self.user_id,
            "day": self._format_day(day),
            "name": name,
            "minutes": minutes,
            "calories": -abs(calories_burned),
            "exerciseId": 0,
            "activityId": 0,
            "activitySpecId": 0,
            "weight": 0,
            "calorieOverride": False,
            "order": 0,
            "meta": {},
        }
        data = self._request("/api/v2/add_exercise", {"exercise": exercise})
        logger.info("Added exercise %s (%d min)", name, minutes)
        return data

    def edit_exercise(
        self,
        exercise_id: int,
        *,
        minutes: int | None = None,
        calories_burned: float | None = None,
        day: date | None = None,
    ) -> dict:
        """Change the duration or burn of a logged exercise.

        Uses: POST /api/v2/edit_exercise
        """
        exercise = self.find_entry(exercise_id, "Exercise", day)
        if minutes is not None:
            exercise["minutes"] = minutes
        if calories_burned is not None:
            exercise["calories"] = -abs(calories_burned)
        data = self._request("/api/v2/edit_exercise", {"exercise": exercise})
        logger.info("Edited exercise %s", exercise_id)
        return data

    # ------------------------------------------------------------------
    # Fasting
    # ------------------------------------------------------------------

    def add_fast(
        self, start: datetime, end: datetime | None = None, goal_hours: float = 16
    ) -> dict:
        """Record a fast. Leaving end unset starts an open, ongoing fast.

        Uses: POST /api/v2/add_fast
        """
        fast = {
            "userId": self.user_id,
            "start": int(start.timestamp() * 1000),
            "goal": int(goal_hours * 3600 * 1000),
        }
        if end is not None:
            fast["end"] = int(end.timestamp() * 1000)
        data = self._request("/api/v2/add_fast", {"fast": fast})
        logger.info("Added fast starting %s", start)
        return data

    def edit_fast(
        self,
        fast_id: int,
        *,
        start: datetime | None = None,
        end: datetime | None = None,
        goal_hours: float | None = None,
    ) -> dict:
        """Change the bounds or goal of a recorded fast. Ends an open fast.

        Uses: POST /api/v2/edit_fast
        """
        fasts = self.get_fasting_with_date_range().get("fasts", [])
        fast = next((f for f in fasts if f.get("id") == fast_id), None)
        if fast is None:
            raise CronometerError(f"No fast with id {fast_id} in the recent range")
        if start is not None:
            fast["start"] = int(start.timestamp() * 1000)
        if end is not None:
            fast["end"] = int(end.timestamp() * 1000)
        if goal_hours is not None:
            fast["goal"] = int(goal_hours * 3600 * 1000)
        data = self._request("/api/v2/edit_fast", {"fast": fast})
        logger.info("Edited fast %s", fast_id)
        return data

    def delete_fast(self, fast_id: int) -> dict:
        """Remove a recorded fast.

        Uses: POST /api/v2/delete_fast
        """
        data = self._request("/api/v2/delete_fast", {"fastId": fast_id})
        logger.info("Deleted fast %s", fast_id)
        return data

    # ------------------------------------------------------------------
    # Targets
    # ------------------------------------------------------------------

    def get_targets(self) -> dict:
        """Nutrient targets for the account, as shown next to the diary totals.

        Uses: POST /api/v2/get_targets
        """
        data = self._request("/api/v2/get_targets", {"config": {"call_version": 1}})
        logger.info("Fetched nutrient targets")
        return data

    def find_target(self, nutrient_id: int) -> dict | None:
        """The current target row for one nutrient, or None if it has none."""
        for row in self.get_targets().get("targets", []):
            if row.get("id") == nutrient_id:
                return row
        return None

    def set_target(
        self,
        nutrient: str,
        *,
        minimum: float | None = None,
        maximum: float | None = None,
        visible: bool | None = None,
        custom: bool | None = None,
    ) -> dict:
        """Set a nutrient's target, its maximum, or whether it is shown.

        edit_target replaces the whole row rather than patching it: a field left
        out of the request is cleared, not kept. So the current row is read and
        merged first, which is what stops "just make iodine visible" from also
        wiping the iodine target that was already there.

        The write field is `cus` while the read field is `custom`, and the two
        are translated here.

        Uses: POST /api/v2/edit_target
        """
        index = self.nutrient_index()
        key = _slug(nutrient)
        key = NUTRIENT_ALIASES.get(key, key)
        entry = index.get(key)
        if entry is None:
            raise CronometerError(
                f"Unknown nutrient: {nutrient}. Call list_nutrients for the names."
            )
        nutrient_id = entry["id"]

        current = self.find_target(nutrient_id) or {}
        merged = {
            "id": nutrient_id,
            "cus": current.get("custom", False),
            "vis": current.get("vis", True),
        }
        if "min" in current:
            merged["min"] = float(current["min"])
        if "max" in current:
            merged["max"] = float(current["max"])

        if minimum is not None:
            merged["min"] = float(minimum)
        if maximum is not None:
            merged["max"] = float(maximum)
        if visible is not None:
            merged["vis"] = bool(visible)
        # Giving a value makes it a custom target unless told otherwise, since
        # that is the only reading of "set protein to 145" that does anything.
        if custom is not None:
            merged["cus"] = bool(custom)
        elif minimum is not None or maximum is not None:
            merged["cus"] = True

        self._request("/api/v2/edit_target", merged)
        logger.info(
            "Set target for %s (id=%d): %s", entry["name"], nutrient_id, merged
        )
        return {
            "nutrient": entry["name"],
            "unit": entry["unit"],
            "target": self.find_target(nutrient_id),
        }


# ======================================================================
# Helpers
# ======================================================================


def _meal_group_for_hour(hour: int) -> int:
    """Map hour of day to a Cronometer diary meal group.

    1 = Breakfast, 2 = Lunch, 3 = Dinner, 4 = Snacks.
    """
    if 4 <= hour < 10:
        return 1  # Breakfast
    elif 10 <= hour < 14:
        return 2  # Lunch
    elif 14 <= hour < 21:
        return 3  # Dinner
    else:
        return 4  # Snacks
