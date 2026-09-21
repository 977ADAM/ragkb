from fastapi import APIRouter, Depends

from ragkb.api.deps.services import search_service
from ragkb.api.schemas.search import SearchRequest
from ragkb.services.search import SearchService

router = APIRouter()


@router.post("/search")
def search(
    req: SearchRequest,
    svc: SearchService = Depends(search_service),
) -> dict:
    return svc.search(req.query, req.top_k)
