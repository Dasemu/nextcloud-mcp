# Deployment

The repo currently ships a `nixpacks.toml` (`python server.py`), i.e. it is
built/run through Nixpacks rather than this org's standard LXC/VPS + systemd
setup.

This does not yet follow the `web-deploy` standard. Missing pieces, if the
deployment target is ever moved to an LXC/VPS:

- A systemd unit file to run `server.py` as a service.
- An idempotent `scripts/update.sh` (pull, install deps, restart).
- An authenticated HTTP endpoint that triggers the update script (token auth,
  single-flight, status, rate limiting).

Until then, deploy via whatever platform consumes `nixpacks.toml` and set the
environment variables listed in `.env.example`.
