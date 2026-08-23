<center align="center" style="text-align: center;justify-content:center;">
<div align="center" style="text-align: center;justify-content:center;">
<h1 align="center" style="text-align: center;justify-content:center;">

Cronometer MCP server

<img style="justify-content:center;text-align: center;width: 95px; height: auto;" width="793" height="411" alt="image" src="https://github.com/user-attachments/assets/abed1a04-d69b-4ab4-a490-d606064df72d" />
<img style="justify-content:center;text-align: center;width: 250px; height: auto;" alt="image" src="https://i.imgur.com/BvK8LSN.png" />

</h1>


![Version](https://img.shields.io/badge/version-1.6.0-blue.svg?style=for-the-badge) ![Python](https://img.shields.io/badge/Python-3776AB?style=for-the-badge&logo=python&logoColor=white) ![Node](https://img.shields.io/badge/Node.js-339933?style=for-the-badge&logo=node.js&logoColor=white) ![OAuth](https://img.shields.io/badge/OAuth_2.1-EB5424?style=for-the-badge&logo=auth0&logoColor=white)

</div>
</center>

<hr>

Read and write your Cronometer food diary from Claude.ai and Claude Code. It talks to `mobile.cronometer.com`, the same API the Cronometer Android app uses, and puts an OAuth 2.1 login in front so you can add it to Claude.ai as a custom connector. Claude Code can use a plain token instead. You do not need a Gold subscription, and there is no limit of ten exports a day like there is with CSV export.

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
| `add_food_entry` | Add a food to a meal |
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
| `add_exercise` | Add an exercise |
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

## How it fits together

```
Claude.ai / Claude Code
        |  HTTPS
   Cloudflare Tunnel, or any proxy that gives you HTTPS
        |
   nginx  127.0.0.1:8431
        |
   auth-server.js  :8432    handles the login and the tokens
        |
   cronometer-mcp  :8430    the server itself, local only
        |
   mobile.cronometer.com
```

The server itself has no login of its own, and it refuses to listen on anything but the local machine. So anything that reaches it has already got past the login. That login accepts either an OAuth token, which is what Claude.ai sets up for you, or a fixed token, which is quicker for Claude Code.

## Install

```bash
git clone https://github.com/rollecode/cronometer-mcp.git
cd cronometer-mcp
./install.sh
```

The installer sets up Python and Node, asks for your Cronometer login and a password for the connector's login page, makes a token, and writes the service files and the nginx site with your own hostname and username filled in.

You need Node 18 or newer, Python 3.12 or newer, and [uv](https://docs.astral.sh/uv/).

Putting the server online is left to you, because this is where setups differ the most, and a wrong guess here would put your food diary on the public internet. Point a tunnel or a proxy at `127.0.0.1:8431`. With Cloudflare Tunnel:

```yaml
ingress:
  - hostname: cronometer-mcp.example.com
    service: http://localhost:8431
```

It has to be HTTPS. OAuth will not work over plain HTTP.

## Self-hosting it by hand

If you would rather see every step than run the installer, this is all of it.
The end state is two services on your own machine, reachable over HTTPS.

### 1. Get the code and its dependencies

```bash
git clone https://github.com/rollecode/cronometer-mcp.git
cd cronometer-mcp
npm install --omit=dev
uv venv && uv pip install -e .
```

### 2. Store your Cronometer login

```bash
./set-credentials.sh
```

It prompts for your email, password and time zone, and writes them to
`~/.config/cronometer-mcp/env` with mode 0600. The password is never echoed and
never reaches your shell history. Do it by hand if you prefer:

```bash
mkdir -p ~/.config/cronometer-mcp && chmod 700 ~/.config/cronometer-mcp
cat > ~/.config/cronometer-mcp/env <<'EOF'
CRONOMETER_USERNAME=you@example.com
CRONOMETER_PASSWORD=your-password
CRONOMETER_ACCOUNT_TZ=Europe/Helsinki
EOF
chmod 600 ~/.config/cronometer-mcp/env
```

Check it works before going further. This logs in and prints your diary:

```bash
set -a && . ~/.config/cronometer-mcp/env && set +a
.venv/bin/python -c "from cronometer_mcp import CronometerClient; c=CronometerClient(); print(c.get_diary()['summary'])"
```

### 3. Set the connector password and a token

The password is what you type on the sign-in page when adding the connector in
Claude.ai. Only its scrypt hash is stored.

```bash
CONFIG_DIR=~/.config/cronometer-mcp node set-password.js 'your-password-here'
```

The token is the shortcut for Claude Code, which sends a header and skips the
browser entirely.

```bash
openssl rand -hex 32 > ~/.config/cronometer-mcp/token
chmod 600 ~/.config/cronometer-mcp/token
```

### 4. Install the two services

`systemd/` holds both unit files. Replace `YOUR_USER` with your username and
`cronometer-mcp.example.com` with your hostname, then:

```bash
mkdir -p ~/.cache/cronometer-mcp
sudo cp systemd/cronometer-mcp.service systemd/cronometer-mcp-auth.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now cronometer-mcp cronometer-mcp-auth
systemctl status cronometer-mcp cronometer-mcp-auth
```

`cronometer-mcp` is the server itself on :8430, reachable only from the machine
it runs on. `cronometer-mcp-auth` is the login layer on :8432, and it is the
only thing that talks to :8430.

One trap worth naming, because the symptom is confusing: do not add
`IPAddressDeny=any` to `cronometer-mcp.service`. It is a sensible hardening line
for a server that only reads local files, but this one has to reach
`mobile.cronometer.com`, and with it set every tool call hangs until it times
out while systemd still reports the service as active. Nothing is gained by it
either, since the server already refuses to listen beyond the local machine.

### 5. Put nginx in front

```bash
sudo cp nginx/cronometer-mcp.conf /etc/nginx/sites-enabled/cronometer-mcp
sudo nginx -t && sudo systemctl reload nginx
```

It listens on `127.0.0.1:8431` and passes everything to the login layer. The
long read timeout and `proxy_buffering off` matter: the MCP holds the connection
open and sends as it goes, and buffering would stall it.

### 6. Give it an HTTPS address

A Cloudflare Tunnel avoids opening a router port. Any HTTPS reverse proxy works
just as well.

```yaml
ingress:
  - hostname: cronometer-mcp.example.com
    service: http://localhost:8431
```

```bash
cloudflared tunnel route dns YOUR_TUNNEL cronometer-mcp.example.com
sudo systemctl restart cloudflared
```

### 7. Check it from outside

```bash
curl https://cronometer-mcp.example.com/.well-known/oauth-authorization-server
curl -o /dev/null -w '%{http_code}\n' -X POST https://cronometer-mcp.example.com/mcp
```

The first returns the login details. The second must return `401`: anything else
means the login layer is being bypassed and your diary is exposed.

Then connect a client as described under [Connecting](#connecting).

### Updating

```bash
git pull
uv pip install -e . && npm install --omit=dev
sudo systemctl restart cronometer-mcp cronometer-mcp-auth
```

After adding or renaming a tool, press Reconnect on the connector in Claude.ai.
That refreshes the tool list inside a conversation you already have open, and
your sign-in survives it, because tokens live in `oauth.db` on disk rather than
in memory.

### When something is wrong

```bash
journalctl -u cronometer-mcp -n 50 --no-pager
journalctl -u cronometer-mcp-auth -n 50 --no-pager
```

| What you see | What it usually is |
| --- | --- |
| Tool calls hang, service says active | `IPAddressDeny` on the MCP unit, see step 4 |
| `401` on every call from Claude Code | Token mismatch, compare the header against `~/.config/cronometer-mcp/token` |
| Sign-in page rejects the password | No hash stored yet, run step 3 |
| Login fails asking for a 2FA code | See [If you use two-factor](#if-you-use-two-factor) |
| `502` from nginx | The login layer is down, `systemctl status cronometer-mcp-auth` |

## Connecting

**Claude.ai.** Go to Settings, Connectors, Add custom connector, and give it `https://your-host/mcp`. Leave the client ID and secret empty. Sign in with the password the installer set. Doing this once covers web, desktop and mobile, because connectors belong to your account rather than one device.

**Claude Code, through the browser:**

```bash
claude mcp add --transport http cronometer https://your-host/mcp --scope user
```

Then run `/mcp` to sign in.

**Claude Code, with a token, no browser:**

```bash
claude mcp add --transport http cronometer https://your-host/mcp \
  --header "Authorization: Bearer $(cat ~/.config/cronometer-mcp/token)" \
  --scope user
```

## Using it without a server at all

If Claude runs on the same machine, skip the web server and the login entirely
and let it start the MCP directly:

```bash
claude mcp add cronometer -- /path/to/cronometer-mcp/.venv/bin/cronometer-mcp
```

It reads your login from `~/.config/cronometer-mcp/env` or from a `.env` file.

## Settings

| Variable | What it is for |
| --- | --- |
| `CRONOMETER_USERNAME` | Your Cronometer email |
| `CRONOMETER_PASSWORD` | Your Cronometer password |
| `CRONOMETER_ACCOUNT_TZ` | The time zone your diary days are counted in |
| `CRONOMETER_TOTP_SECRET` | Your two-factor secret, only if you have two-factor on. Needs the `totp` extra |
| `ISSUER` | The public address of the server |
| `PORT` | Login server port, 8432 by default |
| `UPSTREAM` | Where the MCP server is, `http://127.0.0.1:8430` by default |
| `CONFIG_DIR` | Where the password, token and database are kept |
| `CALL_TIMEOUT_MS` | How long a call may go quiet before it is cut off, 120000 by default |
| `MCP_PORT` | MCP server port, 8430 by default |
| `MCP_PUBLIC_URL` | Public address, used to advertise the icon to clients |

Everything secret lives in `~/.config/cronometer-mcp/`, readable only by you: `env` holds your Cronometer login, `password-hash` the password for the connector's login page, `token` the fixed token, and `oauth.db` the apps and tokens the login server has handed out. Tokens are stored scrambled, so a stolen copy of the database gives nobody a working key.

Your Cronometer session is saved in `~/.cache/cronometer-mcp/session.json`, so restarting the server does not log in again and again and hit Cronometer's limit.

### If you use two-factor

A server left running on its own cannot type a code, so it needs the secret behind the code instead:

```bash
uv pip install -e '.[totp]'
```

Then set `CRONOMETER_TOTP_SECRET` to the secret from your authenticator app. Without it, an account with two-factor turned on will fail to log in and tell you exactly this.

## Working on the code

```bash
uv venv && uv pip install -e . && uv pip install pytest ruff
.venv/bin/python -m pytest tests -q
.venv/bin/python -m ruff check src/ tests/
```

## Credits

The Cronometer client started as a copy of
[rwestergren/cronometer-api-mcp](https://github.com/rwestergren/cronometer-api-mcp).
The login layer comes from
[rollecode/obsidian-remote-mcp](https://github.com/rollecode/obsidian-remote-mcp).
