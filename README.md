# ARIS: Agentic Research Intelligence System

ARIS is an agentic scientific research framework built around a strict Brain/Body split and optimized for the AiiDA ecosystem. Platform code lives in `aris_core`, while application behavior lives in `aris_apps`.

The Brain-side repo lives in `aris/`. The worker remains a separate repo in `../aiida-worker`, with a separate Python environment and no direct code import dependency from ARIS into worker internals.

## Key Features

- Brain/Body split: ARIS orchestrates reasoning and UI workflows; AiiDA-Worker owns `aiida-core`, profiles, submissions, and database access.
- Typed integration boundary: worker responses are normalized into stable JSON payloads before they reach the frontend.
- Engine isolation: `aris_core` stays platform-level, while AiiDA-specific behavior lives under `aris_apps.aiida`.
- Runtime isolation: mutable memories, uploads, caches, and script archives live under `~/.aris/`, while managed chat projects default to `~/.aris/projects`.
## ARIS <-> AiiDA-Worker Protocol

ARIS owns one isolated AiiDA worker child process. The process has its own
Python/AiiDA environment but no web server and no listening port. Requests are
newline-delimited JSON-RPC 2.0 over stdin/stdout.

Capabilities use explicit names such as `runtime.status`, `profile.list`,
`infrastructure.setup`, `submission.validate`, `process.detail`,
`group.export_archive`, `data.import`, and `execution.run_python`. Project,
session, workspace, and interpreter context travel as typed JSON-RPC params.
Binary imports and exports use base64 inside the protocol.

## Local Layout

- Canonical brain repo: `/Users/yimingzhang/Developer/aris-workspace/aris`
- Canonical worker repo: `/Users/yimingzhang/Developer/aris-workspace/aiida-worker`
- Canonical runtime root: `~/.aris`
- Default managed project root: `~/.aris/projects`
- User-writable config overlay: `~/.aris/config`

Backlog and product ideas should go in `/Users/yimingzhang/Developer/aris-workspace/aris/todo`, not in this README.

## Local Operations

- ARIS can run as a standalone macOS application; VS Code is optional.
- Use `./scripts/aris-local.sh start` to start ARIS API, which owns the worker subprocess and serves the production frontend without Vite.
- Use `./scripts/aris-local.sh open-dev` while editing the React frontend; it starts Vite and opens a separate hot-reloading development window.
- Use `./scripts/aris-local.sh status`, `doctor`, `restart`, `stop`, or `logs` for daily operations.
- Run `./scripts/aris-local.sh install` once to build and install `~/Applications/ARIS.app`. Opening the app starts the local services and displays ARIS in a native WebKit window instead of a browser.
- The desktop app stores the current repository path in its application bundle. Run `install` again after moving the repository.
- PM2 manages `aris-api`, `aris-web`, and optionally `aris-tunnel`; it never manages the worker separately.
- The active PM2 ecosystem file is `/Users/yimingzhang/Developer/aris-workspace/aris/ecosystem.config.js`.
- Set `ARIS_PM2_ECOSYSTEM_FILE` only when intentionally testing an alternate process definition.
- Use `/Users/yimingzhang/Developer/aris-workspace/aris/scripts/pm2-dev.sh` for common local PM2 operations:
  `./scripts/pm2-dev.sh start`, `./scripts/pm2-dev.sh restart`, `./scripts/pm2-dev.sh status`, `./scripts/pm2-dev.sh logs web`, `./scripts/pm2-dev.sh startup`.
- The script defaults to the `dev` target, which manages `aris-api` and `aris-web`. Use `core`, `api`, or `web` for a narrower scope.
- `./scripts/pm2-dev.sh startup` writes a user-level `launchd` agent under `~/Library/LaunchAgents/` that runs `pm2 resurrect` on login. Run `./scripts/pm2-dev.sh save` after changing the managed process set.
- AiiDA presets, settings, and specialization manifests can also be overridden under `~/.aris/config/apps/aiida/` without modifying the repo copy.
- The Cloudflare tunnel defaults to `aris-aiida-tunnel`. If your deployed Cloudflare resource still has an older name, set `ARIS_TUNNEL_NAME` before starting PM2.
