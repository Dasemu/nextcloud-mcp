import os
import threading
from datetime import datetime, timezone

import httpx
from mcp.server.mcpserver import MCPServer

UMAMI_HOST = os.environ["UMAMI_HOST"].rstrip("/")
UMAMI_USERNAME = os.environ["UMAMI_USERNAME"]
UMAMI_PASSWORD = os.environ["UMAMI_PASSWORD"]
BIND_HOST = os.environ.get("BIND_HOST", "127.0.0.1")
BIND_PORT = int(os.environ.get("BIND_PORT", "8083"))

METRIC_TYPES = {"url", "referrer", "browser", "os", "device", "country", "event", "query"}

mcp = MCPServer("umami")

_token_lock = threading.Lock()
_token: str | None = None


def _login() -> str:
    global _token
    with httpx.Client(timeout=30.0) as c:
        r = c.post(f"{UMAMI_HOST}/api/auth/login",
                   json={"username": UMAMI_USERNAME, "password": UMAMI_PASSWORD})
        r.raise_for_status()
        _token = r.json()["token"]
        return _token


def _request(method: str, path: str, **kwargs) -> httpx.Response:
    global _token
    with _token_lock:
        if _token is None:
            _login()
    with httpx.Client(timeout=30.0) as c:
        headers = kwargs.pop("headers", {})
        headers["Authorization"] = f"Bearer {_token}"
        r = c.request(method, f"{UMAMI_HOST}/api{path}", headers=headers, **kwargs)
        if r.status_code == 401:
            with _token_lock:
                _login()
            headers["Authorization"] = f"Bearer {_token}"
            r = c.request(method, f"{UMAMI_HOST}/api{path}", headers=headers, **kwargs)
        r.raise_for_status()
        return r


def _to_ms(value: str) -> int:
    """Accept an ISO date/datetime string (e.g. '2026-08-01' or '2026-08-01T00:00:00Z')
    or a raw millisecond epoch string, and return milliseconds since epoch."""
    value = value.strip()
    if value.isdigit():
        return int(value)
    text = value.replace("Z", "+00:00")
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int(dt.timestamp() * 1000)


@mcp.tool()
def list_websites() -> list[dict]:
    """List all Umami websites visible to this account, including websites owned by
    teams/organizations this account owns. Use list_teams + list_team_websites to also
    see websites in teams this account is only a member (not owner) of."""
    r = _request("GET", "/websites", params={"pageSize": 100, "includeTeams": "true"})
    data = r.json().get("data", [])
    return [{"id": w.get("id"), "name": w.get("name"), "domain": w.get("domain"),
              "created_at": w.get("createdAt")} for w in data]


@mcp.tool()
def list_teams() -> list[dict]:
    """List Umami teams/organizations this account belongs to."""
    r = _request("GET", "/teams", params={"pageSize": 100})
    data = r.json().get("data", [])
    return [{"id": t.get("id"), "name": t.get("name")} for t in data]


@mcp.tool()
def list_team_websites(team_id: str) -> list[dict]:
    """List all websites belonging to a specific Umami team/organization (use list_teams
    to find team ids)."""
    r = _request("GET", f"/teams/{team_id}/websites", params={"pageSize": 100})
    data = r.json().get("data", [])
    return [{"id": w.get("id"), "name": w.get("name"), "domain": w.get("domain"),
              "created_at": w.get("createdAt")} for w in data]


@mcp.tool()
def get_website_stats(website_id: str, start_at: str, end_at: str) -> dict:
    """Get summary stats (pageviews, visitors, visits, bounces, total time) for a
    website between start_at and end_at (ISO date/datetime strings, e.g. '2026-08-01')."""
    r = _request("GET", f"/websites/{website_id}/stats",
                 params={"startAt": _to_ms(start_at), "endAt": _to_ms(end_at)})
    return r.json()


@mcp.tool()
def get_pageviews(website_id: str, start_at: str, end_at: str, unit: str = "day",
                   timezone_name: str = "UTC") -> dict:
    """Get pageview and session timeseries for a website between start_at and end_at.
    unit: 'hour'|'day'|'month'. timezone_name: IANA timezone, e.g. 'Europe/Madrid'."""
    r = _request("GET", f"/websites/{website_id}/pageviews",
                 params={"startAt": _to_ms(start_at), "endAt": _to_ms(end_at),
                         "unit": unit, "timezone": timezone_name})
    return r.json()


@mcp.tool()
def get_metrics(website_id: str, start_at: str, end_at: str, metric_type: str,
                 limit: int = 20) -> list[dict]:
    """Get a breakdown of a metric for a website between start_at and end_at.
    metric_type must be one of: url, referrer, browser, os, device, country, event, query."""
    if metric_type not in METRIC_TYPES:
        raise ValueError(f"metric_type must be one of {sorted(METRIC_TYPES)}")
    r = _request("GET", f"/websites/{website_id}/metrics",
                 params={"startAt": _to_ms(start_at), "endAt": _to_ms(end_at),
                         "type": metric_type, "limit": limit})
    return r.json()


@mcp.tool()
def get_active_visitors(website_id: str) -> int:
    """Get the number of currently active (real-time) visitors on a website."""
    r = _request("GET", f"/websites/{website_id}/active")
    data = r.json()
    if isinstance(data, list):
        return len(data)
    return data.get("visitors", data)


if __name__ == "__main__":
    mcp.run(transport="streamable-http", host=BIND_HOST, port=BIND_PORT)
