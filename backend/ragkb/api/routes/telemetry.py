from fastapi import APIRouter, Depends

from ragkb.api.deps.auth import current_user
from ragkb.api.deps.services import telemetry_service
from ragkb.domain.entities import User
from ragkb.services.telemetry import EventBatch, TelemetryService

router = APIRouter()


@router.post("/events")
def log_events(
    batch: EventBatch,
    user: User = Depends(current_user),
    svc: TelemetryService = Depends(telemetry_service),
) -> dict[str, int]:
    return svc.ingest(user, batch)
