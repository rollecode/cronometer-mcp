<center align="center" style="text-align: center;justify-content:center;">
<div align="center" style="text-align: center;justify-content:center;">
<h1 align="center" style="text-align: center;justify-content:center;">

Cronometer MCP server

<img style="justify-content:center;text-align: center;width: 95px; height: auto;" width="793" height="411" alt="image" src="https://github.com/user-attachments/assets/abed1a04-d69b-4ab4-a490-d606064df72d" />
<img style="justify-content:center;text-align: center;width: 250px; height: auto;" alt="image" src="https://i.imgur.com/BvK8LSN.png" />

</h1>


![Version](https://img.shields.io/badge/version-1.9.2-blue.svg?style=for-the-badge) ![Python](https://img.shields.io/badge/Python-3776AB?style=for-the-badge&logo=python&logoColor=white)

</div>
</center>

<hr>

Read and write your Cronometer food diary from Claude.ai and Claude Code. It talks to `mobile.cronometer.com`, the same API the Cronometer Android app uses. You do not need a Gold subscription, and there is no limit of ten exports a day like there is with CSV export.

This fork is a pure Python MCP server, meant to be deployed on [Prefect Horizon](https://www.prefect.io/horizon), which provides the OAuth. The upstream project bundles its own Node login layer instead; `main` here still tracks it.

<hr>

## Why not the other options

* Terra API sends your Cronometer data to a webhook, but it can only read, and your food log passes through someone else's servers
* `gocronometer` and similar export tools can only read, and they are rate limited
* Tools that scrape the Cronometer website can write, but they rely on codes that change every time Cronometer ships an update, and they need Gold

## Tools

### Reading

| Tool | What you get |
| --- | --- |
| `get_food_log` | Everything in the diary for one day. Each food comes with its name, where it came from, the serving size, how many servings, and what that food added to your nutrients. You also get calories (target, eaten, left) and totals for every nutrient you track |
| `get_daily_nutrition` | Totals for every nutrient eaten that day, each flagged tracked or not |
| `get_nutrition_scores` | Cronometer's nutrition scores |
| `search_foods` | Search the food database |
| `get_food_details` | Full nutrients and serving sizes for one food |
| `get_targets` | Your nutrient goals and which nutrients are tracked, named and with units |
| `get_macro_targets` | Your protein, carb and fat goals |
| `list_biometrics` | What you can measure, and the units each one accepts |
| `get_biometrics` | One measurement over time |
| `get_fasting_history` | Fasts between two dates |
| `get_fasting_stats` | Fasting totals and averages |
| `list_nutrients` | Every nutrient you can set on a custom food, with units |
| `get_recent_foods` | Recently logged foods and how often each was logged |
| `get_streak` | Current and record run of fully logged days |
| `get_profile` | Account profile: birthdate, gender, timezone, language |
| `list_custom_foods` | Your whole custom library, no database results mixed in |
| `list_recipes` | Your recipes, each with its serving type |
| `find_entries_by_food` | Every diary entry referencing a food, with dates and amounts |

### Writing

| Tool | What it does |
| --- | --- |
| `add_food_entry` | Add a food to a meal, at a given time of day |
| `edit_food_entry` | Change how much you ate, or when |
| `remove_food_entry` | Delete food entries |
| `add_custom_food` | Create your own food, with up to all 94 nutrients |
| `create_recipe` | Create or update a recipe from ingredients |
| `update_custom_food` | Edit a custom food in place, keeping its diary entries |
| `update_recipe` | Edit a recipe in place, keeping its serving type |
| `retire_custom_food` | Retire a custom food, or bring one back |
| `add_note` | Write a note on a day |
| `edit_note` | Rewrite a note |
| `add_biometric` | Record a measurement such as weight or body fat |
| `edit_biometric` | Fix a measurement you got wrong |
| `remove_biometric` | Delete a measurement, e.g. a broken scale's reading |
| `add_exercise` | Add an exercise |
| `remove_exercise` | Delete exercise entries |
| `edit_exercise` | Change how long an exercise lasted, or how much it burned |
| `add_fast` | Record a fast, finished or still running |
| `edit_fast` | Change a fast's times or goal, including ending one that is still running |
| `delete_fast` | Delete a fast |
| `copy_day` | Copy one day's diary onto another day |
| `mark_day_complete` | Mark a day done, or not done |
| `set_nutrient_target` | Set a nutrient's target or limit, or start tracking it |

### Custom foods

`add_custom_food` takes a dict of nutrient name to amount, so you can give it
anything from one nutrient to the whole catalog in a single call:

```json
{
  "name": "Vaasan Ruispalat",
  "serving_name": "1 slice",
  "serving_grams": 33,
  "nutrients": {
    "energy": 79, "protein": 3.1, "carbs": 12.5, "fiber": 3.4,
    "fat": 0.8, "saturated": 0.2, "salt_g": 0.36,
    "iron": 0.9, "magnesium": 26, "b1_thiamine": 0.09, "folate": 11
  }
}
```

Amounts are for one whole serving, each in that nutrient's own unit. Call
`list_nutrients` for the accepted names, which come from your account's own
catalog rather than a table baked in here.

A nutrient you leave out stays blank in Cronometer. Passing `0` instead states
that the food contains none of it, and the app treats the two differently, so
only pass what you actually know. An unrecognised name is an error rather than
being quietly dropped, because a food that silently lost a nutrient still looks
complete.

Two conveniences the food label has and the catalog does not: `energy_kj` is
converted to calories, and `salt_g` to sodium. Pass one or the other, not both.
`update_custom_food` takes the same keys, so a food written in label units stays
editable in them.

### Recipes

`create_recipe` takes ingredients rather than nutrient values, and Cronometer
sums the nutrition from them itself:

```json
{
  "name": "Overnight oats",
  "servings": 2,
  "ingredients": [
    {"food_id": 450856, "grams": 118},
    {"food_id": 465906, "grams": 80}
  ]
}
```

Find each ingredient's `food_id` with `search_foods` first. Portions log in
plain grams with `add_food_entry`.

Add `cooked_grams` whenever the dish was baked or simmered. Nutrients are stored
per 100 g, so a dish that lost water is denser than its raw ingredients, and
without it a portion weighed off the plate logs too little.

**Cronometer locks a recipe's serving type at creation and it cannot be changed
afterwards**, so `serving_type` matters:

| | `"weight"` (default) | `"servings"` |
| --- | --- | --- |
| Portions | Plain grams everywhere, including the mobile app | Grams through this server; the app offers only a 1 g serving and hides the amount field |
| Ingredients | Recorded in the recipe notes | Editable list in Cronometer |

The split exists because Cronometer derives a recipe's weight only from
ingredients whose measure is weight-typed, and most database foods use
non-weight measures. A real 1802 g recipe came back weighing 446 g, which then
skews every per-100 g value. A weight-based recipe therefore has its nutrients
summed here and is stored as a plain food, which is exactly why it cannot also
carry an editable ingredient list.

### Tracked and untracked nutrients

Cronometer's own daily summary covers only nutrients with a target set. Anything
else is left out entirely, which for a consumer reading the response is
indistinguishable from having eaten none of it. Log a coffee with no caffeine
target set, and the day's summary reports no caffeine at all.

`get_daily_nutrition` and `get_food_log` therefore return everything eaten, and
mark each nutrient with `tracked`:

```json
{"id": 262, "name": "Caffeine", "amount": 80.0, "unit": "mg", "tracked": false}
```

`tracked: false` means no target is set, so the figure stands on its own and
nothing can be said about being over or under. Tracked amounts come from
Cronometer's own totals and match the app; untracked ones are summed from the
day's entries, which reproduces those totals to within rounding.

Pass `include_untracked=false` for the app's narrower view. Depending on how many
targets you have set, that can easily halve the number of nutrients returned.

### Setting targets

`set_nutrient_target` covers both the goal and whether a nutrient is tracked at
all, which is what makes a micronutrient appear in the diary:

```json
{"nutrient": "protein", "minimum": 145}
{"nutrient": "iodine", "visible": true}
{"nutrient": "sodium", "maximum": 2300}
```

Cronometer's endpoint replaces the whole row rather than patching it, so this
reads the nutrient's current settings and merges your change into them. Turning
on visibility therefore keeps whatever target was already set, and each call
reports the previous values alongside the new ones.

### Editing and auditing your library

`update_custom_food` and `update_recipe` patch in place: only what you pass
changes, and entries already logged stay attached to the same food while their
nutrition follows the edit. So a typo, a stripped `ä`, or one wrong nutrient is
fixed without recreating the food and re-logging every entry. Nutrients merge
into the existing profile rather than replacing it.

`list_custom_foods` returns the whole library with nothing from the database
mixed in, which is what makes an audit possible. Before retiring a food, run
`find_entries_by_food` to see where it was logged, or its entries are left
pointing at something retired.

Serving type stays fixed: `update_recipe` will not change it, because
Cronometer locks it at creation.

Neither tool can drop a measure. A measure id is what diary entries point at,
and Cronometer renders an entry whose measure vanished with the amount in the
calorie column and no timestamp, so a write that would lose one is refused
rather than repaired afterwards. Passing `measures` patches the ids you name
and leaves the rest alone.

## Running it

The server is a plain Python MCP server. It has no login of its own: whatever
runs it is responsible for authenticating callers.

### On Prefect Horizon

Horizon terminates OAuth, injects the environment and drives the transport, so
there is nothing to install and no proxy to run.

| Setting | Value |
| --- | --- |
| Entrypoint | `main.py:mcp` |
| Dependencies | detected from `pyproject.toml` |
| Authentication | enable it in Horizon; the server has none of its own |

The entrypoint must be `main.py:mcp`, not `src/cronometer_mcp/server.py:mcp`.
Horizon imports the file by path, which leaves it without package context, and
the package's relative imports fail. `main.py` is a three-line shim that
imports the package by name.

Check it before deploying:

```bash
uv run fastmcp inspect main.py:mcp   # should report 40 tools
```

### Anywhere else

```bash
uv venv && uv pip install -e .
.venv/bin/cronometer-mcp                    # streamable HTTP on $PORT (8430)
.venv/bin/cronometer-mcp --transport stdio  # for a local MCP client
```

Over HTTP it binds `0.0.0.0` and has no authentication, so put something in
front of it or keep the port private.

To let Claude Code start it directly, no server at all:

```bash
claude mcp add cronometer -- /path/to/cronometer-mcp/.venv/bin/cronometer-mcp --transport stdio
```

## Settings

All configuration is environment variables. The server refuses to start and
names what is missing.

| Variable | Required | What it is for |
| --- | --- | --- |
| `CRONOMETER_USERNAME` | yes | Your Cronometer email |
| `CRONOMETER_PASSWORD` | yes | Your Cronometer password |
| `CRONOMETER_ACCOUNT_TZ` | yes | IANA zone your diary days are counted in, e.g. `Europe/Madrid` |
| `CRONOMETER_TOTP_SECRET` | only with 2FA | Two-factor secret. Needs the `totp` extra |
| `PORT` | no | HTTP port, 8430 by default. Ignored on Horizon |
| `HOST` | no | HTTP bind address, `127.0.0.1` by default. Ignored on Horizon |
| `CRONOMETER_ALLOW_PUBLIC_BIND` | no | Set to `1` to allow a non-local `HOST`. The server has no login of its own, so only set it when something in front of it authenticates. Ignored on Horizon |
| `MCP_TRANSPORT` | no | `streamable-http` (default) or `stdio` |
| `CRONOMETER_CACHE_DIR` | no | Where the session cache goes |

For local development a `.env` file in the working directory is read too. Real
environment variables win over it. `.env` is gitignored; keep it that way.

### The session cache

The Cronometer session token is cached at
`<cache dir>/cronometer-mcp/session.json` so restarts do not re-login and hit
Cronometer's rate limit. It is an optimisation, not state: an ephemeral or
read-only filesystem costs one extra login on cold start and nothing else.
Cache dir is `CRONOMETER_CACHE_DIR`, else `XDG_CACHE_HOME`, else `~/.cache`.

### If you use two-factor

A server left running on its own cannot type a code, so it needs the secret
behind the code instead:

```bash
uv pip install -e '.[totp]'
```

Then set `CRONOMETER_TOTP_SECRET` to the secret from your authenticator app.
Without it, an account with two-factor turned on will fail to log in and tell
you exactly this.

## Working on the code

```bash
uv venv && uv pip install -e . && uv pip install pytest ruff
.venv/bin/python -m pytest tests -q
.venv/bin/python -m ruff check src/ tests/ main.py
```

## Credits

The Cronometer client started as a copy of
[rwestergren/cronometer-api-mcp](https://github.com/rwestergren/cronometer-api-mcp).
