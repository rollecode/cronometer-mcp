# Cronometer MCP

Remote MCP server for [Cronometer](https://cronometer.com), with full read and
write access to the food diary. Runs on your own machine and is reachable from
Claude.ai (web, desktop, mobile) as a custom connector and from Claude Code over
HTTP.

Cronometer has no public API. This talks to `mobile.cronometer.com`, the REST
API used by the Cronometer Android app, so no Gold subscription and no export
rate limit is involved.

## What it can do

Read:

- Food log for a day, meal by meal, with food names and per-entry nutrients
- Daily totals across all ~80 tracked nutrients, against your targets
- Nutrition scores
- Food database search and full nutrient profiles for a food
- Macro targets, fasting history and stats, biometric time series

Write:

- Log a serving to any meal, by food and measure
- Remove diary entries
- Create custom foods with a full nutrient breakdown
- Copy a day's diary onto another day
- Mark a day complete

## Architecture

```
Claude.ai / Claude Code
        |  HTTPS
   Cloudflare Tunnel
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
but loopback. Everything reaching it has already passed the auth server.

## Install

```bash
git clone https://github.com/rollecode/cronometer-mcp.git
cd cronometer-mcp
./install.sh
```

`install.sh` creates the venv, installs the Node dependencies, prompts for the
Cronometer login and the connector password, and writes the systemd units and
the nginx site with your real hostname and user.

Then point a tunnel or a reverse proxy at `127.0.0.1:8431`.

## Clients

Claude.ai (covers web, desktop and mobile, it is an account-level setting):
Settings, Connectors, Add custom connector, URL `https://your-host/mcp`.

Claude Code:

```bash
claude mcp add --transport http cronometer https://your-host/mcp --scope user
/mcp
```

Or with the static bearer token from `~/.config/cronometer-mcp/token`, skipping
the browser flow:

```bash
claude mcp add --transport http cronometer https://your-host/mcp \
  --header "Authorization: Bearer $(cat ~/.config/cronometer-mcp/token)" --scope user
```

## Local stdio

For a client on the same machine, skip the HTTP and OAuth layers entirely:

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
| `ISSUER` | Public HTTPS origin of the auth server |
| `PORT` | Auth server port, default 8432 |
| `UPSTREAM` | MCP server URL, default `http://127.0.0.1:8430` |
| `MCP_PORT` | MCP server port, default 8430 |

The session token is cached in `~/.cache/cronometer-mcp/session.json` so
restarts do not trip Cronometer's login rate limit.

## Credits

The Cronometer mobile API client is derived from
[rwestergren/cronometer-api-mcp](https://github.com/rwestergren/cronometer-api-mcp)
(MIT). The OAuth layer is the one from
[rollecode/obsidian-remote-mcp](https://github.com/rollecode/obsidian-remote-mcp).

## Licence

MIT
