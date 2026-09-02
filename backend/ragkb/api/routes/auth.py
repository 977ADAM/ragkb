"""HTTP-слой auth: signup, signin, signout, me, profile, password."""
from fastapi import APIRouter, Request, Response

from ragkb.api.deps import AuthSvc
from ragkb.api.deps.auth import (
    clear_session_cookie,
    current_user,
    get_auth_service,
    raw_cookie,
    set_session_cookie,
)
from ragkb.api.schemas.auth import ChangePassword, Credentials
from ragkb.core.errors import Forbidden

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


@router.get("/profile")
async def profile(request: Request) -> dict:
    """Сведения о себе: имя, роль, дата регистрации (если есть)."""
    if request.app.state.auth.mode == "session":
        svc = get_auth_service(request)
        username, role, created_at = await svc.profile(raw_cookie(request))
        return {
            "username": username,
            "role": role,
            "created_at": created_at.isoformat() if created_at else None,
        }
    user = await current_user(request)
    return {"username": user.name, "role": user.role, "created_at": None}


@router.post("/password", status_code=204)
async def change_password(
    body: ChangePassword,
    request: Request,
    response: Response,
    svc: AuthSvc,
) -> None:
    """Смена пароля локального аккаунта. В proxy-режиме недоступна."""
    if request.app.state.auth.mode != "session":
        raise Forbidden("Смена пароля доступна только локальным аккаунтам")
    await svc.change_password(
        raw_cookie(request), body.current_password, body.new_password
    )
