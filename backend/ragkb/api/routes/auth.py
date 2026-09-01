"""HTTP-слой auth: signup, signin, signout, me."""
from this import s

from fastapi import APIRouter, Request, Response, status

from ragkb.api.deps import AuthSvc
from ragkb.api.deps.auth import clear_session_cookie, raw_cookie, set_session_cookie
from ragkb.api.schemas.auth import Credentials, UserRresponse, MessageResponse
from ragkb.platform.auth import current_user

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/signup", response_model=UserRresponse, status_code=status.HTTP_201_CREATED)
async def signup(
    body: Credentials,
    request: Request,
    response: Response,
    svc: AuthSvc,
) -> UserRresponse:
    username, token = await svc.register(body.username, body.password)
    await svc.logout(raw_cookie(request))
    set_session_cookie(response, request, token)
    return UserRresponse(
        id=0,
        email="",
        username=username,
        created_at=None
    )


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


@router.post("/signout", response_description=MessageResponse, status_code=204)
async def signout(
    request: Request,
    response: Response,
    svc: AuthSvc,
) -> MessageResponse:
    await svc.logout(raw_cookie(request))
    clear_session_cookie(response, request)
    return MessageResponse(message="Выход выполнен")


@router.get("/me", response_model=UserRresponse)
async def me(
    request: Request,
    svc: AuthSvc
) -> UserRresponse:
    if request.app.state.auth.mode == "session":
        username = await svc.me(raw_cookie(request))
    else:
        username = (await current_user(request)).name

    return UserRresponse(
        id=0,
        email="",
        username=username,
        created_at=None
    )
