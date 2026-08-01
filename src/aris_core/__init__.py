"""Canonical ARIS core package exports."""

from src.aris_core.config import Settings, settings
from src.aris_core.capabilities import CapabilityRegistry, capability_registry
from src.aris_core.memory import JSONMemory

__all__ = [
    "CapabilityRegistry",
    "JSONMemory",
    "Settings",
    "capability_registry",
    "settings",
]
