"""Правило зависимостей слоёв — красный тест, не замечание на ревью."""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PKG = ROOT / "ragkb"
MIGRATIONS = ROOT / "migrations"

ALLOWED_TOP_DIRS = {"api", "core", "db", "domain", "services"}


def _imports(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.append(node.module)
    return names


def _py_files(root: Path) -> list[Path]:
    return [p for p in root.rglob("*.py") if "__pycache__" not in p.parts]


def test_package_has_only_five_layer_dirs():
    top = {p.name for p in PKG.iterdir() if p.is_dir() and "__pycache__" not in p.name}
    assert top == ALLOWED_TOP_DIRS


def test_core_does_not_import_upper_layers():
    forbidden = ("ragkb.api", "ragkb.db", "ragkb.domain", "ragkb.services")
    for path in _py_files(PKG / "core"):
        for name in _imports(path):
            for prefix in forbidden:
                assert not name.startswith(prefix), f"{path} импортирует {name}"


def test_domain_does_not_import_upper_layers():
    forbidden = (
        "fastapi",
        "sqlalchemy",
        "pydantic",
        "ragkb.api",
        "ragkb.db",
        "ragkb.services",
        "ragkb.core",
    )
    for path in _py_files(PKG / "domain"):
        for name in _imports(path):
            for prefix in forbidden:
                assert not name.startswith(prefix), f"{path} импортирует {name}"


def test_services_do_not_import_http_or_orm():
    _assert_not_imported(
        PKG / "services",
        ("fastapi", "sqlalchemy", "ragkb.api", "ragkb.db", "ragkb.core.database"),
    )


def test_api_does_not_import_orm():
    _assert_not_imported(PKG / "api", ("sqlalchemy", "ragkb.db"))


def test_routes_do_not_import_core_or_ports():
    for path in (PKG / "api" / "routes").rglob("*.py"):
        for name in _imports(path):
            if name == "ragkb.core.errors":
                continue
            assert not name.startswith("ragkb.core"), path
            assert not name.endswith(".ports"), path


def test_db_does_not_import_http_or_services():
    _assert_not_imported(PKG / "db", ("fastapi", "ragkb.api", "ragkb.services"))


def test_sqlalchemy_not_in_core():
    forbidden = ("sqlalchemy", "alembic")
    for path in _py_files(PKG / "core"):
        if path.name == "database.py":
            continue
        for name in _imports(path):
            root = name.split(".")[0]
            assert root not in forbidden, path
    for path in _py_files(MIGRATIONS):
        for name in _imports(path):
            if name.startswith("ragkb.") and not name.startswith(
                ("ragkb.core.config", "ragkb.core.database", "ragkb.db")
            ):
                pytest.fail(f"{path} импортирует {name}")


def _assert_not_imported(root: Path, prefixes: tuple[str, ...]) -> None:
    if not root.is_dir():
        return
    for path in _py_files(root):
        for name in _imports(path):
            for prefix in prefixes:
                assert not name.startswith(prefix), f"{path} импортирует {name}"


def test_expected_revision_matches_alembic_head():
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    from ragkb.core.database import EXPECTED_REVISION

    script = ScriptDirectory.from_config(Config(str(ROOT / "alembic.ini")))
    assert script.get_current_head() == EXPECTED_REVISION


def test_each_alembic_revision_creates_one_table() -> None:
    import re

    found: list[str] = []
    for path in sorted((MIGRATIONS / "versions").glob("*.py")):
        names = set(re.findall(r"CREATE TABLE (\w+)", path.read_text(), re.I))
        if not names:
            continue
        assert len(names) == 1, f"{path.name} создаёт {sorted(names)}"
        found.append(names.pop())
    assert found == [
        "conversations",
        "messages",
        "cleanup_state",
        "users",
        "sessions",
    ]


def test_revision_0006_alters_users_role() -> None:
    text = (MIGRATIONS / "versions" / "0006_user_role.py").read_text()
    assert "role" in text.lower()
    assert "0005_sessions" in text
