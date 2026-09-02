from __future__ import annotations


def test_get_admin_credentials_none_when_empty(monkeypatch):
    monkeypatch.delenv("ADMIN_LOGIN", raising=False)
    monkeypatch.delenv("ADMIN_PASSWORD", raising=False)
    from ragkb.core.security import get_admin_credentials
    assert get_admin_credentials() is None


def test_get_admin_credentials_normalizes_login(monkeypatch):
    monkeypatch.setenv("ADMIN_LOGIN", "Ada")
    monkeypatch.setenv("ADMIN_PASSWORD", "password1")
    from ragkb.core.security import get_admin_credentials
    assert get_admin_credentials() == ("ada", "password1")


def test_get_admin_credentials_none_when_password_too_short(monkeypatch, caplog):
    monkeypatch.setenv("ADMIN_LOGIN", "admin")
    monkeypatch.setenv("ADMIN_PASSWORD", "short")
    from ragkb.core.security import get_admin_credentials

    with caplog.at_level("WARNING"):
        assert get_admin_credentials() is None
    assert caplog.records


def test_get_admin_credentials_none_when_login_invalid(monkeypatch):
    monkeypatch.setenv("ADMIN_LOGIN", "Bad Login")
    monkeypatch.setenv("ADMIN_PASSWORD", "password1")
    from ragkb.core.security import get_admin_credentials
    assert get_admin_credentials() is None
