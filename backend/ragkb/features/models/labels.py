"""Подпись модели для списка в UI."""
from __future__ import annotations

from pathlib import Path


def model_label(model_id: str, title: str | None = None) -> str:
    if title:
        return title
    if "/" in model_id or "\\" in model_id:
        name = Path(model_id).name
        return name or model_id
    return model_id
