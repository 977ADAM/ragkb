"""Аутентификация."""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from starlette.datastructures import Headers

from ragkb.core.config import AuthConfig
from ragkb.platform.auth import User, parse_groups, user_from_headers
from ragkb.platform.errors import Forbidden, Unauthenticated


def test_parse_groups_comma_and_repeats():
    assert parse_groups(["a, b", "b", "c"]) == ("a", "b", "c")


def test_user_from_headers():
    cfg = AuthConfig()
    user = user_from_headers(
        Headers(
            {
                cfg.header: "ada",
                cfg.email_header: "ada@ex",
                cfg.groups_header: "ragkb-users,ragkb-admins",
            }
        ),
        cfg,
    )
    assert user == User(
        name="ada", email="ada@ex", groups=("ragkb-users", "ragkb-admins")
    )


def test_missing_header_is_none():
    assert user_from_headers(Headers({}), AuthConfig()) is None


def test_admin_forbidden(indexed):
    from fastapi.testclient import TestClient

    from ragkb.platform.app import create_app

    indexed.auth.mode = "proxy"
    with TestClient(create_app(indexed)) as client:
        headers = {"X-Forwarded-Preferred-Username": "bob"}
        assert client.post("/index/rebuild", headers=headers).status_code == 403
    assert isinstance(Forbidden("x"), Exception)
    assert isinstance(Unauthenticated("x"), Exception)


def test_auth_service_rejects_missing_accounts():
    from ragkb.api.deps.auth import get_auth_service

    request = SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(
                container=SimpleNamespace(
                    accounts=None, _ensure_postgres=lambda: None
                )
            )
        )
    )
    with pytest.raises(RuntimeError, match="Postgres не подключён"):
        get_auth_service(request)
