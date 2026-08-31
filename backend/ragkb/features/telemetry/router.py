from fastapi import APIRouter, Depends

from ragkb.features.telemetry.service import EventBatch, TelemetryService
from ragkb.platform.auth import User, current_user
from ragkb.platform.deps import telemetry_service

router = APIRouter()


@router.post("/events")
def log_events(
    batch: EventBatch,
    user: User = Depends(current_user),
    svc: TelemetryService = Depends(telemetry_service),
) -> dict[str, int]:
    return svc.ingest(user, batch)
