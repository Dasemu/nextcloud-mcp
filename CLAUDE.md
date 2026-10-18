# CLAUDE.md

## Overview
MCP server exposing a Nextcloud instance (files, calendars, address books,
Talk) as tools for an MCP-compatible AI agent. Single file: `server.py`.

## Commands
- Install: `pip install -r requirements.txt`
- Run: `python server.py` (reads `NEXTCLOUD_HOST`, `NEXTCLOUD_USERNAME`,
  `NEXTCLOUD_PASSWORD` from the environment; see `.env.example`)
- Test: none yet.
- Lint: none yet.
- Build: none (no packaging step; Nixpacks runs `python server.py` directly,
  see `nixpacks.toml`).
- Sanity check: `python -m py_compile server.py`

## Architecture
See [`docs/architecture.md`](docs/architecture.md).

## Conventions
- One `@mcp.tool()` function per Nextcloud operation; docstring = tool
  description shown to the agent.
- Parsing/formatting helpers are private (`_`-prefixed) and live near the
  tools that use them.

## Workflow quirks
- No `development` branch yet; branch from `main`, PR into `main` directly
  until `development` is created.
- No automated tests or linter are configured yet (no pytest/ruff/flake8 in
  `requirements.txt`). CI only runs `python -m py_compile server.py` as a
  sanity check.

## Deployment
See [`docs/deployment.md`](docs/deployment.md). Currently deployed via
Nixpacks, not the org's standard LXC/VPS + systemd setup.

## Gotchas
- `NEXTCLOUD_HOST`, `NEXTCLOUD_USERNAME`, `NEXTCLOUD_PASSWORD` are required
  env vars; the process raises `KeyError` on import if any is missing.
- Recurring calendar events are expanded server-side (`c:expand`) in
  `list_events`, so each occurrence is a separate item, unlike `get_event`.
