"""Версия пакета — `project.version` из backend/pyproject.toml."""
from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

_PYPROJECT = Path(__file__).resolve().parents[1] / "pyproject.toml"


def _from_pyproject(path: Path) -> str:
    in_project = False
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped == "[project]":
            in_project = True
            continue
        if stripped.startswith("["):
            in_project = False
            continue
        if in_project and stripped.startswith("version"):
            return stripped.split("=", 1)[1].strip().strip('"').strip("'")
    raise RuntimeError(f"Нет project.version в {path}")


if _PYPROJECT.is_file():
    __version__ = _from_pyproject(_PYPROJECT)
else:
    try:
        __version__ = version("ragkb")
    except PackageNotFoundError as exc:
        raise RuntimeError(
            "Версия ragkb: нужен pyproject.toml или установленный пакет"
        ) from exc
