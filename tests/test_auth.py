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
