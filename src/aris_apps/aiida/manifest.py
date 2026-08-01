from __future__ import annotations

from importlib import import_module

from src.aris_apps.aiida.paths import logs_template, static_dir
from src.aris_core.plugins import StaticMount


class AiiDAAppManifest:
    name = "aiida"
    api_prefix = "/api/aiida"
    agent_module = "src.aris_apps.aiida.agent.researcher"
    deps_module = "src.aris_apps.aiida.deps"
    static_mounts = (
        StaticMount(url_path="/static", directory=static_dir(), name="static"),
    )
    logs_template = logs_template()

    def include_routes(self, app) -> None:
        root_router = import_module("src.aris_apps.aiida.api.root_routes").router
        api_router = import_module("src.aris_apps.aiida.api.router").router
        app.include_router(root_router)
        app.include_router(api_router, prefix=self.api_prefix)

    def register_capabilities(self, registry) -> None:
        capability_module = import_module("src.aris_apps.aiida.capabilities")
        registry.register("aiida", capability_module.aiida_capability)

    def register_runtime(self, active_hubs: list[object]) -> None:
        hub_module = import_module("src.aris_apps.aiida.hub")
        hub = getattr(hub_module, "hub", None)
        if hub is not None:
            active_hubs.append(hub)


manifest = AiiDAAppManifest()
