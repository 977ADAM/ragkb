"""Кеш списка диалогов для consistency=eventual."""
from __future__ import annotations

import time
from collections import OrderedDict
from typing import Any, TypeVar

K = TypeVar("K")
EVENTUAL_TTL_SEC = 5.0
_MAX = 256


class EventualCache:
    def __init__(self, ttl: float = EVENTUAL_TTL_SEC, maxsize: int = _MAX):
        self.ttl = ttl
        self.maxsize = maxsize
        self._data: OrderedDict[K, tuple[float, Any]] = OrderedDict()

    def get(self, key: K) -> Any | None:
        hit = self._data.get(key)
        if hit is None:
            return None
        expires, value = hit
        if expires <= time.monotonic():
            self._data.pop(key, None)
            return None
        self._data.move_to_end(key)
        return value

    def set(self, key: K, value: Any) -> None:
        self._data[key] = (time.monotonic() + self.ttl, value)
        self._data.move_to_end(key)
        while len(self._data) > self.maxsize:
            self._data.popitem(last=False)
