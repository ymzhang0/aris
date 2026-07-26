from __future__ import annotations

import pytest
from fastapi import HTTPException

from src.aris_apps.aiida import service as aiida_service


def _capabilities_payload() -> dict[str, object]:
    return {
        "aiida_core_version": "2.7.3",
        "available_transports": ["core.local", "core.ssh", "core.ssh_async"],
        "recommended_transport": "core.ssh_async",
        "supports_async_ssh": True,
        "transport_auth_fields": {
            "core.local": ["use_login_shell", "safe_interval"],
            "core.ssh": [
                "username",
                "port",
                "look_for_keys",
                "key_filename",
                "timeout",
                "allow_agent",
                "proxy_jump",
                "proxy_command",
                "compress",
                "gss_auth",
                "gss_kex",
                "gss_deleg_creds",
                "gss_host",
                "load_system_host_keys",
                "key_policy",
                "use_login_shell",
                "safe_interval",
            ],
            "core.ssh_async": ["host", "max_io_allowed", "authentication_script", "backend", "use_login_shell", "safe_interval"],
        },
    }


@pytest.mark.anyio
async def test_parse_infrastructure_yaml_accepts_asyncssh_fields(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _fake_capabilities() -> dict[str, object]:
        return _capabilities_payload()

    monkeypatch.setattr(aiida_service.aiida_worker_client, "get_infrastructure_capabilities", _fake_capabilities)
    monkeypatch.setattr(
        aiida_service.infrastructure_manager,
        "merge_preset",
        lambda parsed: {"matched": False, "config": parsed},
    )

    parsed = await aiida_service.parse_infrastructure_via_ai(
        """
label: daint
hostname: daint.cscs.ch
transport: core.ssh_async
scheduler: core.slurm
work_dir: /scratch/{username}/aiida
auth:
  host: daint-login
  max_io_allowed: 12
  authentication_script: /usr/local/bin/2fa.sh
  backend: openssh
  use_login_shell: false
  safe_interval: 2.5
""",
    )

    assert parsed["type"] == "computer"
    assert parsed["computer"]["transport_type"] == "core.ssh_async"
    assert parsed["computer"]["host"] == "daint-login"
    assert parsed["computer"]["authentication_script"] == "/usr/local/bin/2fa.sh"
    assert parsed["computer"]["backend"] == "openssh"
    assert parsed["computer"]["use_login_shell"] is False


@pytest.mark.anyio
async def test_parse_infrastructure_yaml_rejects_core_ssh_fields_for_asyncssh(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _fake_capabilities() -> dict[str, object]:
        return _capabilities_payload()

    monkeypatch.setattr(aiida_service.aiida_worker_client, "get_infrastructure_capabilities", _fake_capabilities)
    monkeypatch.setattr(
        aiida_service.infrastructure_manager,
        "merge_preset",
        lambda parsed: {"matched": False, "config": parsed},
    )

    with pytest.raises(HTTPException) as exc_info:
        await aiida_service.parse_infrastructure_via_ai(
            """
label: daint
hostname: daint.cscs.ch
transport: core.ssh_async
scheduler: core.slurm
auth:
  username: alice
""",
        )

    assert exc_info.value.status_code == 422
    assert "core.ssh_async" in str(exc_info.value.detail)
    assert "username" in str(exc_info.value.detail)


@pytest.mark.anyio
async def test_parse_infrastructure_uses_selected_ssh_host_without_ai(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _fake_capabilities() -> dict[str, object]:
        return _capabilities_payload()

    monkeypatch.setattr(aiida_service.aiida_worker_client, "get_infrastructure_capabilities", _fake_capabilities)
    monkeypatch.setattr(
        aiida_service.infrastructure_manager,
        "merge_preset",
        lambda parsed: {"matched": False, "config": parsed},
    )

    parsed = await aiida_service.parse_infrastructure_via_ai(
        "",
        {
            "alias": "daint-login",
            "hostname": "daint.cscs.ch",
            "username": "alice",
            "identity_file": "/Users/alice/.ssh/id_ed25519",
        },
    )

    assert parsed["computer"]["label"] == "daint-login"
    assert parsed["computer"]["transport_type"] == "core.ssh_async"
    assert parsed["computer"]["host"] == "daint-login"
    assert parsed["computer"]["hostname"] == "daint.cscs.ch"
