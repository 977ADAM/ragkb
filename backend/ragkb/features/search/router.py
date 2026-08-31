from fastapi import APIRouter, Depends

from ragkb.features.search.service import SearchRequest, SearchService
from ragkb.platform.auth import User, current_user
from ragkb.platform.deps import search_service

router = APIRouter()


@router.post("/search")
def search(
    req: SearchRequest,
    user: User = Depends(current_user),
    svc: SearchService = Depends(search_service),
) -> dict:
    return svc.search(req.query, req.top_k)
