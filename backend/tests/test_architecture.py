"""Правило зависимостей слайсов — красный тест, не замечание на ревью."""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PKG = ROOT / "ragkb"
MIGRATIONS = ROOT / "migrations"


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


def test_core_does_not_import_features_or_platform():
    for path in _py_files(PKG / "core"):
        for name in _imports(path):
            assert not name.startswith("ragkb.features"), path
            assert not name.startswith("ragkb.platform"), path


def test_feature_routers_do_not_import_core_or_ports():
    for path in (PKG / "features").rglob("router.py"):
        for name in _imports(path):
            assert not name.startswith("ragkb.core"), path
            assert not name.endswith(".ports"), path


def test_feature_services_do_not_import_other_features():
    for path in (PKG / "features").rglob("service.py"):
        slice_name = path.parent.name
        if slice_name == "bootstrap":
            continue
        for name in _imports(path):
            if name.startswith("ragkb.features.") and not name.startswith(
                f"ragkb.features.{slice_name}"
            ):
                pytest.fail(f"{path} импортирует чужой слайс {name}")


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
                ("ragkb.core.config", "ragkb.core.database", "ragkb.features.", "ragkb.db")
            ):
                pytest.fail(f"{path} импортирует {name}")


def _assert_not_imported(root: Path, prefixes: tuple[str, ...]) -> None:
    if not root.is_dir():
        return
    for path in _py_files(root):
        for name in _imports(path):
            for prefix in prefixes:
                assert not name.startswith(prefix), f"{path} импортирует {name}"


def test_domain_depends_only_on_stdlib():
    _assert_not_imported(
        PKG / "domain",
        (
            "fastapi",
            "sqlalchemy",
            "pydantic",
            "ragkb.api",
            "ragkb.db",
            "ragkb.services",
            "ragkb.features",
            "ragkb.platform",
            "ragkb.core",
        ),
    )


def test_services_do_not_import_http_or_orm():
    _assert_not_imported(
        PKG / "services",
        ("fastapi", "sqlalchemy", "ragkb.api", "ragkb.db", "ragkb.features"),
    )


def test_api_does_not_import_orm():
    _assert_not_imported(PKG / "api", ("sqlalchemy", "ragkb.db"))


def test_db_does_not_import_fastapi_or_features():
    _assert_not_imported(PKG / "db", ("fastapi", "ragkb.features", "ragkb.api"))


def test_expected_revision_matches_alembic_head():
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    from ragkb.platform.db import EXPECTED_REVISION

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
