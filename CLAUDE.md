# CLAUDE.md

## Overview
MCP server exposing Umami analytics (pageviews, metrics, active visitors) as tools over
streamable-HTTP, for use by MCP clients (e.g. Claude).

## Commands
- Dev: `python server.py` (reads `UMAMI_HOST`, `UMAMI_USERNAME`, `UMAMI_PASSWORD` from env; see `.env.example`)
- Install: `pip install -r requirements.txt`
- Test: no test suite yet
- Lint: no linter configured yet
- Build: none (plain Python, run directly; `nixpacks.toml` defines the start command for Nixpacks-based hosting)

## Architecture
Single-file server (`server.py`) built on `mcp.server.mcpserver.MCPServer`. Logs into the
Umami API on first request, caches the bearer token in memory, and re-authenticates once on
a 401. Each `@mcp.tool()` function wraps one Umami REST endpoint. See `docs/` for more.

## Conventions
- Keep all tools as thin wrappers around the Umami API; push validation (e.g. `metric_type`)
  into the tool function, not into `_request`.
- Dates/times accepted from callers are ISO strings or raw millisecond epochs (`_to_ms`).

## Workflow quirks
- No tests or linter are set up; CI only compiles the source as a sanity check.

## Deployment
Currently started via Nixpacks (`nixpacks.toml` → `python server.py`). This does not yet
follow the standard LXC/VPS + systemd + authenticated update-endpoint setup described in the
`web-deploy` skill; see `LESSONS.md`.

## Gotchas
- `UMAMI_HOST`, `UMAMI_USERNAME`, `UMAMI_PASSWORD` are required; the process raises on import
  if any is missing (no defaults).
