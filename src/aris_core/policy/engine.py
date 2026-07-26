"""Provider-neutral authorization policy boundary."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

import casbin
from pydantic import BaseModel, Field


class PolicySubject(BaseModel):
    identifier: str
    roles: tuple[str, ...] = Field(default_factory=tuple)


class AuthorizationDecision(BaseModel):
    subject: str
    roles: tuple[str, ...]
    resource: str
    action: str
    allowed: bool
    policy_provider: str


class AuthorizationPolicy(Protocol):
    def decide(
        self,
        subject: PolicySubject,
        *,
        resource: str,
        action: str,
    ) -> AuthorizationDecision: ...


class CasbinAuthorizationPolicy:
    """Casbin adapter; application code depends only on AuthorizationPolicy."""

    def __init__(self, model_file: str | Path, policy_file: str | Path) -> None:
        self._enforcer = casbin.Enforcer(str(model_file), str(policy_file))

    def decide(
        self,
        subject: PolicySubject,
        *,
        resource: str,
        action: str,
    ) -> AuthorizationDecision:
        normalized_roles = tuple(
            role if role.startswith("role:") else f"role:{role}"
            for raw_role in subject.roles
            if (role := raw_role.strip())
        )
        allowed = any(
            bool(self._enforcer.enforce(role, resource, action))
            for role in normalized_roles
        )
        return AuthorizationDecision(
            subject=subject.identifier,
            roles=normalized_roles,
            resource=resource,
            action=action,
            allowed=allowed,
            policy_provider="casbin",
        )
