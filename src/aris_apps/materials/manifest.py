from __future__ import annotations

from importlib import import_module


class MaterialsAppManifest:
    name = "materials"
    api_prefix = "/api/materials"
    static_mounts = ()

    def include_routes(self, app) -> None:
        router = import_module("src.aris_apps.materials.routes").router
        app.include_router(router, prefix=self.api_prefix, tags=["Materials"])

    def register_capabilities(self, registry) -> None:
        capability_module = import_module("src.aris_apps.materials.capability")
        registry.register("materials", capability_module.materials_capability)

    def register_runtime(self, active_hubs: list[object]) -> None:  # noqa: ARG002
        return None


manifest = MaterialsAppManifest()
