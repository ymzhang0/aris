# ARIS for macOS

The macOS target is a small native AppKit/WebKit shell for ARIS. In normal use,
it starts the API, which owns its AiiDA worker subprocess, waits for the ARIS
health check, and
loads the production React build served by the API. It does not start Vite.

Build and install it with:

```bash
./scripts/aris-local.sh install
```

The default destination is `~/Applications/ARIS.app`. Override it with
`ARIS_APP_INSTALL_DIR` when needed.

The application icon is generated from `desktop/macos/assets/aris.png` during
installation. The browser uses the matching assets under `frontend/public`.

The app intentionally does not stop the services when its window closes. This
keeps AiiDA and long-running calculations alive and makes subsequent launches
fast. Stop them explicitly with:

```bash
./scripts/aris-local.sh stop
```

For frontend development with Vite hot reload, use:

```bash
./scripts/aris-local.sh open-dev
```

This starts Vite and opens a separate `ARIS — Development` window. Changes to
the React source appear without rebuilding the app. The normal application
continues to use the last production build.
