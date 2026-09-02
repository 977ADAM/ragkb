from fastapi import APIRouter, Depends

from ragkb.api.deps.auth import current_user
from ragkb.api.deps.services import search_service
from ragkb.api.schemas.search import SearchRequest
from ragkb.domain.entities import User
from ragkb.services.search import SearchService

router = APIRouter()


@router.post("/search")
def search(
    req: SearchRequest,
    user: User = Depends(current_user),
    svc: SearchService = Depends(search_service),
) -> dict:
    return svc.search(req.query, req.top_k)
