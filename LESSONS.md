# LESSONS.md

Recurring mistakes in this repo and how to avoid them.

- Deployment is currently Nixpacks-based (`nixpacks.toml`), not the standard LXC/VPS +
  systemd + authenticated update-endpoint setup described by the `web-deploy` skill. Before
  changing deployment, confirm with the user whether to migrate it or leave Nixpacks as-is;
  don't silently add a systemd unit/update script without asking.
