from src.aris_core.plugins.loader import _parse_enabled_app_names


def test_aiida_is_enabled_by_default(monkeypatch) -> None:
    monkeypatch.delenv("ARIS_ENABLED_APPS", raising=False)

    assert _parse_enabled_app_names() == ("aiida",)


def test_enabled_apps_can_be_overridden(monkeypatch) -> None:
    monkeypatch.setenv("ARIS_ENABLED_APPS", "alpha, beta,alpha")

    assert _parse_enabled_app_names() == ("alpha", "beta")
