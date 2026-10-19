# cloud-mcp

MCP server that exposes a Nextcloud instance (files, calendars, address books,
and Talk) as tools for an MCP-compatible AI agent.

## Quick start

```bash
pip install -r requirements.txt
cp .env.example .env   # fill in NEXTCLOUD_HOST, NEXTCLOUD_USERNAME, NEXTCLOUD_PASSWORD
python server.py
```

See [`docs/architecture.md`](docs/architecture.md) for how it works and
[`docs/deployment.md`](docs/deployment.md) for running it in production.
