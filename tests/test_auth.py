"""Тесты идентификации. Запуск: python tests/test_auth.py"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ragkb.auth import ANONYMOUS, User, parse_groups


# ------------------------------------------------------------- разбор групп

def test_parse_groups_splits_comma_separated():
    assert parse_groups(["ragkb-admins, hr ,legal"]) == ("ragkb-admins", "hr", "legal")


def test_parse_groups_handles_repeated_headers():
    assert parse_groups(["ragkb-admins", "hr"]) == ("ragkb-admins", "hr")


def test_parse_groups_drops_empty_and_duplicates():
    assert parse_groups(["hr,,hr", "   ", "legal"]) == ("hr", "legal")


def test_parse_groups_on_empty_input():
    assert parse_groups([]) == ()


# -------------------------------------------------------------------- User

def test_user_in_group():
    user = User(name="ivanov", groups=("hr", "ragkb-admins"))
    assert user.in_group("ragkb-admins")
    assert not user.in_group("legal")


def test_user_defaults_have_no_groups():
    assert User(name="ivanov").groups == ()


def test_anonymous_name_is_defined():
    assert ANONYMOUS == "anonymous"


# --------------------------------------------------- разбор заголовков

from starlette.datastructures import Headers

from ragkb.auth import current_user, optional_user, require_admin, user_from_headers
from ragkb.config import AuthConfig


def _headers(**pairs) -> Headers:
    return Headers(raw=[(k.lower().replace("_", "-").encode(), v.encode())
                        for k, v in pairs.items()])


def test_user_from_headers_reads_configured_header():
    headers = Headers(raw=[
        (b"x-forwarded-preferred-username", b"ivanov"),
        (b"x-forwarded-email", b"ivanov@example.com"),
        (b"x-forwarded-groups", b"ragkb-admins,hr"),
    ])
    user = user_from_headers(headers, AuthConfig())
    assert user is not None
    assert user.name == "ivanov"
    assert user.email == "ivanov@example.com"
    assert user.in_group("ragkb-admins")


def test_user_from_headers_without_header_returns_none():
    assert user_from_headers(Headers(raw=[]), AuthConfig()) is None


def test_user_from_headers_ignores_blank_name():
    headers = Headers(raw=[(b"x-forwarded-preferred-username", b"   ")])
    assert user_from_headers(headers, AuthConfig()) is None


def test_user_from_headers_respects_custom_header_name():
    cfg = AuthConfig(header="X-My-User")
    headers = Headers(raw=[(b"x-my-user", b"petrov")])
    user = user_from_headers(headers, cfg)
    assert user is not None and user.name == "petrov"


# ------------------------------------------------------------ зависимости

class _FakeRequest:
    """Минимальная замена Request: зависимостям нужны только headers и app.state."""

    class _State:
        def __init__(self, auth): self.auth = auth

    class _App:
        def __init__(self, auth): self.state = _FakeRequest._State(auth)

    def __init__(self, cfg: AuthConfig, headers: Headers | None = None):
        self.headers = headers if headers is not None else Headers(raw=[])
        self.app = _FakeRequest._App(cfg)


def test_current_user_raises_401_without_header():
    from fastapi import HTTPException
    try:
        current_user(_FakeRequest(AuthConfig()))
    except HTTPException as exc:
        assert exc.status_code == 401
    else:
        raise AssertionError("ожидался 401")


def test_current_user_returns_anonymous_when_disabled():
    user = current_user(_FakeRequest(AuthConfig(mode="disabled")))
    assert user.name == ANONYMOUS


def test_optional_user_returns_none_instead_of_raising():
    assert optional_user(_FakeRequest(AuthConfig())) is None


def test_require_admin_raises_403_without_group():
    from fastapi import HTTPException
    headers = Headers(raw=[(b"x-forwarded-preferred-username", b"ivanov"),
                           (b"x-forwarded-groups", b"hr")])
    try:
        require_admin(_FakeRequest(AuthConfig(), headers))
    except HTTPException as exc:
        assert exc.status_code == 403
    else:
        raise AssertionError("ожидался 403")


def test_require_admin_passes_with_group():
    headers = Headers(raw=[(b"x-forwarded-preferred-username", b"ivanov"),
                           (b"x-forwarded-groups", b"ragkb-admins")])
    user = require_admin(_FakeRequest(AuthConfig(), headers))
    assert user.name == "ivanov"


def test_auth_config_defaults_to_proxy_mode():
    assert AuthConfig().mode == "proxy"


def test_config_exposes_auth_section():
    from ragkb.config import Config
    cfg = Config.from_dict({"auth": {"mode": "disabled", "admin_group": "боссы"}})
    assert cfg.auth.mode == "disabled"
    assert cfg.auth.admin_group == "боссы"


# ------------------------------------------------------- эндпоинты чтения

def _client(mode: str = "proxy"):
    """Приложение поверх заведомо отсутствующего индекса.

    index_dir указывает в несуществующий каталог намеренно: у Config значение
    по умолчанию — «data/index», а он в репозитории есть, и тогда часть проверок
    пошла бы не по той ветке. Обработчиков это не касается — зависимости
    идентификации отрабатывают раньше, до обращения к пайплайну.
    """
    import tempfile

    from fastapi.testclient import TestClient

    from ragkb.api import create_app
    from ragkb.config import Config

    cfg = Config()
    cfg.index_dir = str(Path(tempfile.gettempdir()) / "ragkb-нет-такого-индекса")
    cfg.auth.mode = mode
    return TestClient(create_app(cfg), raise_server_exceptions=False)


def test_ask_requires_authentication():
    resp = _client().post("/ask", json={"question": "тест"})
    assert resp.status_code == 401, resp.status_code


def test_search_requires_authentication():
    resp = _client().post("/search", json={"query": "тест"})
    assert resp.status_code == 401, resp.status_code


def test_ask_stream_requires_authentication():
    resp = _client().post("/ask/stream", json={"question": "тест"})
    assert resp.status_code == 401, resp.status_code


def test_index_page_requires_authentication():
    assert _client().get("/").status_code == 401


def test_index_page_open_when_auth_disabled():
    assert _client("disabled").get("/").status_code == 200


if __name__ == "__main__":
    failed = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"  ok   {name}")
            except Exception as exc:
                failed += 1
                print(f"  FAIL {name}: {type(exc).__name__}: {exc}")
    print(f"\n{'все тесты пройдены' if not failed else f'провалов: {failed}'}")
    raise SystemExit(1 if failed else 0)
