from __future__ import annotations

from collections.abc import Iterator
from typing import Any


class CapabilityRegistry:
    """Registry of canonical services contributed by enabled ARIS apps."""

    def __init__(self) -> None:
        self._capabilities: dict[str, Any] = {}

    def register(self, name: str, capability: Any, *, replace: bool = False) -> None:
        normalized = str(name or "").strip()
        if not normalized:
            raise ValueError("Capability name is required")
        if capability is None:
            raise ValueError(f"Capability '{normalized}' cannot be None")
        if normalized in self._capabilities and not replace:
            if self._capabilities[normalized] is capability:
                return
            raise ValueError(f"Capability '{normalized}' is already registered")
        self._capabilities[normalized] = capability

    def get(self, name: str, default: Any = None) -> Any:
        return self._capabilities.get(str(name or "").strip(), default)

    def require(self, name: str) -> Any:
        normalized = str(name or "").strip()
        capability = self.get(normalized)
        if capability is None:
            raise LookupError(f"Capability '{normalized}' is not registered")
        return capability

    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self._capabilities))

    def items(self) -> Iterator[tuple[str, Any]]:
        for name in self.names():
            yield name, self._capabilities[name]

    def clear(self) -> None:
        self._capabilities.clear()


capability_registry = CapabilityRegistry()


__all__ = ["CapabilityRegistry", "capability_registry"]
