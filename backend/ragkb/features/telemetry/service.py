from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from ragkb.features.telemetry.ports import EventSink
from ragkb.platform.auth import User

EVENT_BATCH_LIMIT = 100
EVENT_NAME_LIMIT = 64
EVENT_PROPS_LIMIT = 2000


class ClientEvent(BaseModel):
    name: str = Field(..., min_length=1, max_length=EVENT_NAME_LIMIT)
    ts: str | None = None
    props: dict[str, Any] = Field(default_factory=dict)

    @field_validator("props")
    @classmethod
    def limit_size(cls, value: dict[str, Any]) -> dict[str, Any]:
        if len(json.dumps(value, ensure_ascii=False)) > EVENT_PROPS_LIMIT:
            raise ValueError(f"Свойства события длиннее {EVENT_PROPS_LIMIT} символов")
        return value


class EventBatch(BaseModel):
    session_id: UUID
    events: list[ClientEvent] = Field(..., min_length=1, max_length=EVENT_BATCH_LIMIT)


class TelemetryService:
    def __init__(self, sink: EventSink):
        self.sink = sink

    def ingest(self, user: User, batch: EventBatch) -> dict[str, int]:
        received_at = datetime.now(timezone.utc).isoformat()
        for event in batch.events:
            self.sink.emit(
                {
                    "event": event.name,
                    "user": user.name,
                    "session_id": str(batch.session_id),
                    "ts": event.ts,
                    "received_at": received_at,
                    "props": event.props,
                }
            )
        return {"accepted": len(batch.events)}
