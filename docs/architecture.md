# Architecture

## Overview

`server.py` is a single-file MCP server built with `mcp.server.mcpserver.MCPServer`. It
exposes the Umami analytics REST API as MCP tools so an MCP client can query website stats
without talking to Umami directly.

## Auth flow

- On first request, `_login()` POSTs credentials to `UMAMI_HOST/api/auth/login` and caches
  the returned bearer token in the module-level `_token` variable, guarded by `_token_lock`.
- `_request()` attaches the cached token to every call. On a `401`, it re-logs in once and
  retries the request before giving up.

## Tools

| Tool | Umami endpoint | Notes |
|---|---|---|
| `list_websites` | `GET /websites` | Includes websites from owned teams. |
| `list_teams` | `GET /teams` | Teams/organizations the account belongs to. |
| `list_team_websites` | `GET /teams/{id}/websites` | Websites in a team the account is a member (not owner) of. |
| `get_website_stats` | `GET /websites/{id}/stats` | Pageviews, visitors, visits, bounces, time. |
| `get_pageviews` | `GET /websites/{id}/pageviews` | Timeseries; `unit` is `hour`/`day`/`month`. |
| `get_metrics` | `GET /websites/{id}/metrics` | `metric_type` restricted to `METRIC_TYPES`. |
| `get_active_visitors` | `GET /websites/{id}/active` | Real-time visitor count. |

Dates are accepted as ISO date/datetime strings or raw millisecond epochs, normalized by
`_to_ms`.

## Transport

Runs as `streamable-http` via `mcp.run(...)`, bound to `BIND_HOST`/`BIND_PORT`
(defaults `127.0.0.1:8083`).

## Deployment

Currently started via Nixpacks (`nixpacks.toml`: `python server.py`). This has not yet been
brought in line with the standard LXC/VPS + systemd + authenticated update-endpoint setup
(see root `LESSONS.md`); no systemd unit, update script, or update endpoint exist yet.
