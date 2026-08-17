# Cronometer MCP

Remote MCP server for [Cronometer](https://cronometer.com), with read and write
access to the food diary. Runs on your own machine and is reachable from
Claude.ai (web, desktop and mobile) as a custom connector, and from Claude Code
over HTTP.

Cronometer has no public API. This talks to `mobile.cronometer.com`, the REST
API the Cronometer Android app uses, so there is no Gold requirement and none of
the ten-exports-per-day limit that the CSV export route runs into.

## Why not the alternatives

* Terra API pushes Cronometer data to a webhook, but it is read-only and puts
  the food log through a third party
* `gocronometer` and similar export wrappers are read-only and rate limited
* GWT-RPC scrapers of the web app can write, but depend on build-specific hashes
  that change whenever Cronometer deploys, and need a Gold account

## Tools

### Reading

| Tool | What it returns |
| --- | --- |
| `get_food_log` | Every diary entry for a day. Servings carry the food name, source, measure, servings eaten and that food's own nutrient contribution. Also a day-level energy summary (target, consumed, remaining) and totals for every tracked nutrient |
| `get_daily_nutrition` | Macro and micronutrient totals for a day |
| `get_nutrition_scores` | Cronometer's nutrition confidence scores |
| `search_foods` | Food database search |
| `get_food_details` | Full nutrient profile and serving measures for one food |
| `get_targets` | Nutrient targets shown beside the diary totals |
| `get_macro_targets` | Macro targets and schedules |
| `list_biometrics` | Trackable biometric metrics with their valid unit IDs |
| `get_biometrics` | Time series for one biometric metric |
| `get_fasting_history` | Recorded fasts over a date range |
| `get_fasting_stats` | Aggregate fasting statistics |

### Writing

| Tool | What it does |
| --- | --- |
| `add_food_entry` | Log a serving to a meal slot |
| `edit_food_entry` | Change a logged serving's amount or time |
| `remove_food_entry` | Delete logged servings |
| `add_custom_food` | Create a custom food with a full nutrient breakdown |
| `add_note` | Add a diary note |
| `edit_note` | Rewrite a diary note |
| `add_biometric` | Record a measurement such as weight or body fat |
| `edit_biometric` | Correct a recorded measurement |
| `add_exercise` | Log an exercise entry |
| `edit_exercise` | Change a logged exercise's duration or burn |
| `add_fast` | Record a fast, open-ended or closed |
| `edit_fast` | Change a fast's bounds or goal, including ending an open one |
| `delete_fast` | Remove a recorded fast |
| `copy_day` | Copy one day's diary onto another |
| `mark_day_complete` | Mark a day complete or incomplete |

### What cannot be deleted

Cronometer's mobile API only deletes servings and fasts. Its diary-entry
endpoint accepts a note, biometric or exercise and answers `204` without
removing anything, and no other delete endpoint for those types exists.

So notes, biometrics and exercise entries can be created and corrected here but
not removed. A wrong one has to be edited to the right value, or deleted in the
Cronometer app. The tool descriptions say so, to stop a model promising a
deletion it cannot perform.

## Architecture

```
Claude.ai / Claude Code
        |  HTTPS
   Cloudflare Tunnel or any HTTPS reverse proxy
        |
   nginx  127.0.0.1:8431
        |
   auth-server.js  :8432    OAuth 2.1, PKCE, DCR, static bearer token
        |
   cronometer-mcp  :8430    Streamable HTTP, loopback only
        |
   mobile.cronometer.com
```

The MCP process has no authentication of its own and refuses to bind anything
but loopback, so everything that reaches it has already passed the auth server.
The auth server accepts either an OAuth token, which is what Claude.ai
negotiates, or a static bearer token, which is the quicker path for Claude Code.

## Install

```bash
git clone https://github.com/rollecode/cronometer-mcp.git
cd cronometer-mcp
./install.sh
```

The installer creates the Python venv, installs the Node dependencies, asks for
the Cronometer login and a password for the connector's login page, generates a
static token, and writes the systemd units and the nginx site with your real
hostname and user filled in.

Requires Node 18 or newer, Python 3.12 or newer, and [uv](https://docs.astral.sh/uv/).

Exposing the endpoint is left to you, because that is the step where setups
differ most and guessing wrong publishes a food diary by accident. Point a
tunnel or reverse proxy at `127.0.0.1:8431`. With Cloudflare Tunnel:

```yaml
ingress:
  - hostname: cronometer-mcp.example.com
    service: http://localhost:8431
```

OAuth 2.1 requires HTTPS, so a plain HTTP origin will not work.

## Connecting

Claude.ai, which covers web, desktop and mobile in one go because connectors are
an account-level setting: Settings, Connectors, Add custom connector, URL
`https://your-host/mcp`. Leave client ID and secret blank. Authorize with the
password the installer set.

Claude Code, browser flow:

```bash
claude mcp add --transport http cronometer https://your-host/mcp --scope user
```

Then `/mcp` to authenticate.

Claude Code, static token, skipping the browser:

```bash
claude mcp add --transport http cronometer https://your-host/mcp \
  --header "Authorization: Bearer $(cat ~/.config/cronometer-mcp/token)" \
  --scope user
```

## Local stdio

For a client on the same machine, skip HTTP and OAuth entirely:

```bash
claude mcp add cronometer -- /path/to/cronometer-mcp/.venv/bin/cronometer-mcp
```

Credentials come from `~/.config/cronometer-mcp/env` or a local `.env`.

## Configuration

| Variable | Purpose |
| --- | --- |
| `CRONOMETER_USERNAME` | Cronometer account email |
| `CRONOMETER_PASSWORD` | Cronometer account password |
| `CRONOMETER_ACCOUNT_TZ` | IANA zone the diary days are computed in |
| `CRONOMETER_TOTP_SECRET` | Base32 2FA secret, only if the account has 2FA on. Needs the `totp` extra |
| `ISSUER` | Public HTTPS origin of the auth server |
| `PORT` | Auth server port, default 8432 |
| `UPSTREAM` | MCP server URL, default `http://127.0.0.1:8430` |
| `CONFIG_DIR` | Where the password hash, token and OAuth database live |
| `CALL_TIMEOUT_MS` | How long a proxied call may go silent before it is cut, default 120000 |
| `MCP_PORT` | MCP server port, default 8430 |

Secrets live in `~/.config/cronometer-mcp/`, mode 0600: `env` for the Cronometer
login, `password-hash` for the connector login page, `token` for the static
bearer token, and `oauth.db` for issued OAuth clients and tokens. Tokens are
stored hashed.

The Cronometer session token is cached in `~/.cache/cronometer-mcp/session.json`
so restarts do not trip Cronometer's login rate limit.

### Two-factor authentication

An unattended server cannot type a code, so a 2FA account needs the shared
secret instead:

```bash
uv pip install -e '.[totp]'
```

and set `CRONOMETER_TOTP_SECRET` to the base32 secret from your authenticator.
Without it, a 2FA account fails login with a message saying exactly that.

## Development

```bash
uv venv && uv pip install -e . && uv pip install pytest ruff
.venv/bin/python -m pytest tests -q
.venv/bin/python -m ruff check src/ tests/
```

## Credits

The Cronometer mobile API client is derived from
[rwestergren/cronometer-api-mcp](https://github.com/rwestergren/cronometer-api-mcp).
The OAuth layer comes from
[rollecode/obsidian-remote-mcp](https://github.com/rollecode/obsidian-remote-mcp).
Both MIT, as is this.
