# AiiDA App (Canonical Path)

Current canonical app layout:

```text
src/aris_apps/aiida/
├── api/              # FastAPI assembly and root routes
├── agent/            # Researcher agent, prompts, and worker-backed tools
├── chat/             # Chat session orchestration and workspace state
├── presenters/       # Frontend-facing payload shaping
├── client.py         # Canonical worker client facade
├── service.py        # Service facade for hub/frontend helpers
├── frontend_bridge.py
├── hub.py
├── deps.py
├── config.py
├── schema.py
├── schemas.py
├── specializations.py
└── static/           # Canonical app static assets
```

New implementation work should land here.
