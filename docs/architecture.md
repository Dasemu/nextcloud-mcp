# Architecture

`server.py` is a single-file MCP server (streamable-http transport, via the
`mcp` package's `MCPServer`) that proxies calls to a Nextcloud instance.

## Layers

- **Files**: WebDAV (`PROPFIND`, `GET`, `PUT`, `DELETE`, `MKCOL`, `MOVE`) under
  `/remote.php/dav/files/{user}/`, plus the unified search OCS endpoint and
  the file-sharing OCS API.
- **Calendars**: CalDAV under `/remote.php/dav/calendars/{user}/`. Events and
  tasks (VTODO) are built/parsed with `vobject`. `list_events` uses a
  server-side `calendar-query` with `c:expand` so recurring events come back
  as individual occurrences.
- **Address books**: CardDAV under `/remote.php/dav/addressbooks/users/{user}/`,
  contacts as vCards via `vobject`.
- **Talk**: Nextcloud Talk's OCS Spreed API (`/ocs/v2.php/apps/spreed/api/`)
  for listing conversations and reading/sending chat messages.

All Nextcloud calls use HTTP Basic auth (`NEXTCLOUD_USERNAME` /
`NEXTCLOUD_PASSWORD`) through a short-lived `httpx.Client` per request
(`_client()`).

## Adding a tool

Add a function decorated with `@mcp.tool()`; its docstring becomes the tool
description shown to the agent. Keep request/response shaping (XML/vCard/
iCalendar parsing) in a private helper near the existing `_parse_*` /
`_summarize_*` functions so tools stay thin.
