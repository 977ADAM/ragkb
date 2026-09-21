from fastapi import APIRouter, Depends

from ragkb.api.deps.services import telemetry_service
from ragkb.services.telemetry import EventBatch, TelemetryService

router = APIRouter()


@router.post("/events")
def log_events(
    batch: EventBatch,
    svc: TelemetryService = Depends(telemetry_service),
) -> dict[str, int]:
    return svc.ingest(batch)
