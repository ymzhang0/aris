"""FastAPI adapter for the ARIS authorization policy."""

from __future__ import annotations

from collections.abc import Callable

from fastapi import HTTPException, Request

from src.aris_core.config import settings
from src.aris_core.logging import log_event
from src.aris_core.policy import (
    AuthorizationDecision,
    AuthorizationSnapshot,
    CasbinAuthorizationPolicy,
    PolicySubject,
)

from loguru import logger

authorization_policy = CasbinAuthorizationPolicy(
    settings.ARIS_POLICY_MODEL_FILE,
    settings.ARIS_POLICY_FILE,
)

LOCAL_PERMISSION_TARGETS: dict[str, tuple[str, str]] = {
    "submission.execute": ("/aris/submissions/current", "execute"),
    "submission.cancel": ("/aris/submissions/current", "cancel"),
    "infrastructure.configure": ("/aris/infrastructure/computers", "configure"),
    "profile.configure": ("/aris/profiles", "configure"),
    "profile.switch": ("/aris/profiles/current", "switch"),
    "group.delete": ("/aris/groups/item", "delete"),
    "node.delete": ("/aris/nodes/item", "delete"),
    "chat.delete": ("/aris/chat/items", "delete"),
}


def local_policy_subject() -> PolicySubject:
    return PolicySubject(
        identifier=settings.ARIS_LOCAL_ACTOR_ID,
        roles=(settings.ARIS_LOCAL_ROLE,),
    )


def local_authorization_snapshot() -> AuthorizationSnapshot:
    subject = local_policy_subject()
    decisions = {
        key: authorization_policy.decide(
            subject,
            resource=resource,
            action=action,
        )
        for key, (resource, action) in LOCAL_PERMISSION_TARGETS.items()
    }
    first_decision = next(iter(decisions.values()), None)
    return AuthorizationSnapshot(
        subject=subject.identifier,
        roles=first_decision.roles if first_decision is not None else subject.roles,
        policy_provider=first_decision.policy_provider if first_decision is not None else "unknown",
        permissions={
            key: decision.allowed
            for key, decision in decisions.items()
        },
    )


def require_permission(
    resource: str,
    action: str,
) -> Callable[[Request], AuthorizationDecision]:
    async def dependency(request: Request) -> AuthorizationDecision:
        decision = authorization_policy.decide(
            local_policy_subject(),
            resource=resource,
            action=action,
        )
        logger.info(
            log_event(
                "aris.authorization.decision",
                subject=decision.subject,
                roles=list(decision.roles),
                resource=decision.resource,
                action=decision.action,
                allowed=decision.allowed,
                path=request.url.path,
            )
        )
        if not decision.allowed:
            raise HTTPException(
                status_code=403,
                detail={
                    "error": "Permission denied",
                    "resource": resource,
                    "action": action,
                },
            )
        return decision

    return dependency


__all__ = [
    "authorization_policy",
    "local_authorization_snapshot",
    "local_policy_subject",
    "require_permission",
]
