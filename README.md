# umami-analytics-mcp

MCP server that exposes Umami analytics data (websites, pageviews, metrics, active
visitors) as tools, over streamable-HTTP.

## Quick start

```bash
pip install -r requirements.txt
cp .env.example .env   # fill in your Umami credentials
python server.py
```

See `docs/` for architecture notes and `CLAUDE.md` for conventions and commands.
