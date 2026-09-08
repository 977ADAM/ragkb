"""Лимит multipart: Starlette по умолчанию режет часть на 1 МиБ."""
from __future__ import annotations

from ragkb.services.documents import MAX_UPLOAD_BYTES

MULTIPART_MAX_PART_SIZE = MAX_UPLOAD_BYTES + 1024 * 1024


def raise_multipart_part_limit() -> None:
    from starlette.requests import Request as StarletteRequest

    if getattr(StarletteRequest.form, "_ragkb_max_part_size", None) == MULTIPART_MAX_PART_SIZE:
        return
    original = StarletteRequest.form

    def form(self, *args, **kwargs):
        kwargs.setdefault("max_part_size", MULTIPART_MAX_PART_SIZE)
        return original(self, *args, **kwargs)

    form._ragkb_max_part_size = MULTIPART_MAX_PART_SIZE  # type: ignore[attr-defined]
    StarletteRequest.form = form
