from typing import Any, Protocol


class EventSink(Protocol):
    def emit(self, payload: dict[str, Any]) -> None: ...
