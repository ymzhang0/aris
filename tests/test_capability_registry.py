from __future__ import annotations

import pytest

from src.aris_core.capabilities import CapabilityRegistry


def test_capability_registry_registers_peer_app_services() -> None:
    registry = CapabilityRegistry()
    aiida = object()
    materials = object()

    registry.register("aiida", aiida)
    registry.register("materials", materials)

    assert registry.names() == ("aiida", "materials")
    assert registry.require("aiida") is aiida
    assert registry.require("materials") is materials


def test_capability_registry_rejects_conflicting_implementations() -> None:
    registry = CapabilityRegistry()
    registry.register("materials", object())

    with pytest.raises(ValueError, match="already registered"):
        registry.register("materials", object())
