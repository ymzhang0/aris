"""FastAPI adapter for the ARIS authorization policy."""

from __future__ import annotations

from collections.abc import Callable

from fastapi import HTTPException, Request

from src.aris_core.config import settings
from src.aris_core.logging import log_event
from src.aris_core.policy import (
    AuthorizationDecision,
    CasbinAuthorizationPolicy,
    PolicySubject,
)

from loguru import logger

authorization_policy = CasbinAuthorizationPolicy(
    settings.ARIS_POLICY_MODEL_FILE,
    settings.ARIS_POLICY_FILE,
)


def local_policy_subject() -> PolicySubject:
    return PolicySubject(
        identifier=settings.ARIS_LOCAL_ACTOR_ID,
        roles=(settings.ARIS_LOCAL_ROLE,),
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
    "local_policy_subject",
    "require_permission",
]

