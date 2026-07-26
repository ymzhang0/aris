from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from src.aris_apps.aiida import authorization as authorization_adapter
from src.aris_core.policy import (
    AuthorizationDecision,
    CasbinAuthorizationPolicy,
    PolicySubject,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
MODEL_FILE = REPO_ROOT / "config" / "policy" / "model.conf"
POLICY_FILE = REPO_ROOT / "config" / "policy" / "policy.csv"


def _policy() -> CasbinAuthorizationPolicy:
    return CasbinAuthorizationPolicy(MODEL_FILE, POLICY_FILE)


def test_owner_can_perform_all_protected_actions() -> None:
    decision = _policy().decide(
        PolicySubject(identifier="local-user", roles=("owner",)),
        resource="/aris/infrastructure/computers",
        action="configure",
    )

    assert decision.allowed is True
    assert decision.roles == ("role:owner",)
    assert decision.policy_provider == "casbin"


def test_operator_can_submit_but_cannot_configure_infrastructure() -> None:
    policy = _policy()
    subject = PolicySubject(identifier="operator-1", roles=("operator",))

    assert policy.decide(
        subject,
        resource="/aris/submissions/current",
        action="execute",
    ).allowed is True
    assert policy.decide(
        subject,
        resource="/aris/infrastructure/computers",
        action="configure",
    ).allowed is False


def test_viewer_is_denied_mutating_actions_by_default() -> None:
    decision = _policy().decide(
        PolicySubject(identifier="viewer-1", roles=("viewer",)),
        resource="/aris/chat/sessions",
        action="delete",
    )

    assert decision.allowed is False


@pytest.mark.anyio
async def test_fastapi_adapter_returns_structured_forbidden_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class DenyPolicy:
        def decide(self, subject, *, resource: str, action: str):
            return AuthorizationDecision(
                subject=subject.identifier,
                roles=("role:viewer",),
                resource=resource,
                action=action,
                allowed=False,
                policy_provider="test",
            )

    monkeypatch.setattr(authorization_adapter, "authorization_policy", DenyPolicy())
    monkeypatch.setattr(
        authorization_adapter,
        "local_policy_subject",
        lambda: PolicySubject(identifier="viewer-1", roles=("viewer",)),
    )
    dependency = authorization_adapter.require_permission(
        "/aris/submissions/current",
        "execute",
    )
    request = SimpleNamespace(url=SimpleNamespace(path="/api/aiida/submission/submit"))

    with pytest.raises(HTTPException) as exc_info:
        await dependency(request)

    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == {
        "error": "Permission denied",
        "resource": "/aris/submissions/current",
        "action": "execute",
    }

