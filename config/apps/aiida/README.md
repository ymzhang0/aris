AiiDA application configuration:
- `presets.yaml`
- `settings.yaml`
- `specializations/`

Runtime overrides should live under `~/.aris/config/apps/aiida/`:
- `~/.aris/config/apps/aiida/presets.yaml`
- `~/.aris/config/apps/aiida/settings.yaml`
- `~/.aris/config/apps/aiida/specializations/`

Repo-local files remain the built-in defaults and are copied into `~/.aris/config/`
on first startup when the user-writable copy does not exist yet.
