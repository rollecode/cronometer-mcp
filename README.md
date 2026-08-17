<center align="center" style="text-align: center;justify-content:center;">
<div align="center" style="text-align: center;justify-content:center;">
<h1 align="center" style="text-align: center;justify-content:center;">

Cronometer MCP server

<img style="justify-content:center;text-align: center;width: 95px; height: auto;" width="793" height="411" alt="image" src="https://github.com/user-attachments/assets/abed1a04-d69b-4ab4-a490-d606064df72d" />
<img style="justify-content:center;text-align: center;width: 250px; height: auto;" alt="image" src="https://i.imgur.com/BvK8LSN.png" />

</h1>


![Version](https://img.shields.io/badge/version-1.1.0-blue.svg?style=for-the-badge) ![Python](https://img.shields.io/badge/Python-3776AB?style=for-the-badge&logo=python&logoColor=white) ![Node](https://img.shields.io/badge/Node.js-339933?style=for-the-badge&logo=node.js&logoColor=white) ![OAuth](https://img.shields.io/badge/OAuth_2.1-EB5424?style=for-the-badge&logo=auth0&logoColor=white)

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
| `get_daily_nutrition` | Nutrient totals for one day |
| `get_nutrition_scores` | Cronometer's nutrition scores |
| `search_foods` | Search the food database |
| `get_food_details` | Full nutrients and serving sizes for one food |
| `get_targets` | The nutrient goals shown next to your daily totals |
| `get_macro_targets` | Your protein, carb and fat goals |
| `list_biometrics` | What you can measure, and the units each one accepts |
| `get_biometrics` | One measurement over time |
| `get_fasting_history` | Fasts between two dates |
| `get_fasting_stats` | Fasting totals and averages |
| `list_nutrients` | Every nutrient you can set on a custom food, with units |

### Writing

| Tool | What it does |
| --- | --- |
| `add_food_entry` | Add a food to a meal |
| `edit_food_entry` | Change how much you ate, or when |
| `remove_food_entry` | Delete food entries |
| `add_custom_food` | Create your own food, with up to all 94 nutrients |
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

Cronometer has no delete for foods, so `retire_custom_food` is how one goes
away: it stops being offered for new entries while existing diary entries that
reference it keep working.

### What you cannot delete

Cronometer's app API can only delete foods and fasts. If you ask it to delete a note, a measurement or an exercise, it says it worked and then nothing happens. There is no other way to delete them.

So you can add and change notes, measurements and exercises here, but you cannot remove them. To get rid of one, either edit it to the right value or delete it in the Cronometer app. The tools say this in their own descriptions, so Claude will not promise you a deletion it cannot do.

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

## Running it on your own machine

If Claude is on the same machine, you can skip the web server and the login:

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
