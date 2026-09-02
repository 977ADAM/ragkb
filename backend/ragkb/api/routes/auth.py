"""HTTP-слой auth: signup, signin, signout, me."""
from fastapi import APIRouter, Request, Response

from ragkb.api.deps import AuthSvc
from ragkb.api.deps.auth import (
    clear_session_cookie,
    get_auth_service,
    raw_cookie,
    set_session_cookie,
)
from ragkb.api.schemas.auth import Credentials
from ragkb.platform.auth import current_user

router = APIRouter()


@router.post("/signup")
async def signup(
    body: Credentials,
    request: Request,
    response: Response,
    svc: AuthSvc,
) -> dict[str, str]:
    username, token = await svc.register(body.username, body.password)
    await svc.logout(raw_cookie(request))
    set_session_cookie(response, request, token)
    return {"username": username}


@router.post("/signin")
async def signin(
    body: Credentials,
    request: Request,
    response: Response,
    svc: AuthSvc,
) -> dict[str, str]:
    username, token = await svc.login(body.username, body.password)
    await svc.logout(raw_cookie(request))
    set_session_cookie(response, request, token)
    return {"username": username}


@router.post("/signout", status_code=204)
async def signout(
    request: Request,
    response: Response,
    svc: AuthSvc,
) -> None:
    await svc.logout(raw_cookie(request))
    clear_session_cookie(response, request)


@router.get("/me")
async def me(request: Request) -> dict[str, str]:
    if request.app.state.auth.mode == "session":
        svc = get_auth_service(request)
        username, role = await svc.me(raw_cookie(request))
        return {"username": username, "role": role}
    user = await current_user(request)
    return {"username": user.name, "role": user.role}
