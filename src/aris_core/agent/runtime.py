"""Provider-neutral contract for invoking an ARIS agent."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Protocol, runtime_checkable


@dataclass(frozen=True)
class AgentRetryPolicy:
    """Retry behavior exposed by a runtime adapter."""

    unavailable_retries: int = 0
    base_backoff_seconds: float = 2.0


@dataclass(frozen=True)
class AgentRunRequest:
    """One application-level agent invocation."""

    prompt: str
    deps: Any
    model_name: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AgentRunResult:
    """SDK-independent result returned to application services."""

    output: Any
    provider: str
    model_name: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)


class AgentModelRejectedError(RuntimeError):
    """The configured provider rejected the requested model."""

    def __init__(self, *, provider: str, model_name: str | None, detail: str) -> None:
        self.provider = provider
        self.model_name = model_name
        self.detail = detail
        super().__init__(
            f"{provider} rejected model '{model_name or 'default'}'. {detail}".strip()
        )


@runtime_checkable
class AgentRuntime(Protocol):
    """Small boundary implemented by PydanticAI, OpenAI, or future runtimes."""

    provider: str
    retry_policy: AgentRetryPolicy

    async def run(self, request: AgentRunRequest) -> AgentRunResult:
        """Run one turn and return a provider-neutral result."""

    def is_retryable_unavailable_error(self, error: Exception) -> bool:
        """Return whether a transient provider-unavailable error can be retried."""


__all__ = [
    "AgentModelRejectedError",
    "AgentRetryPolicy",
    "AgentRunRequest",
    "AgentRunResult",
    "AgentRuntime",
]
