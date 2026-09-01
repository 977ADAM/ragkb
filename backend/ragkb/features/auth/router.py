from __future__ import annotations

from fastapi import APIRouter, Depends, Request, Response

from ragkb.features.auth.passwords import COOKIE_NAME, SESSION_DAYS
from ragkb.features.auth.schemas import Credentials
from ragkb.features.auth.service import AuthService
from ragkb.platform.auth import current_user
from ragkb.platform.deps import auth_service

router = APIRouter(prefix="/auth", tags=["auth"])


def _cookie_secure(request: Request) -> bool:
    forwarded = request.headers.get("x-forwarded-proto", "").split(",")[0].strip()
    return request.url.scheme == "https" or forwarded == "https"


def set_session_cookie(response: Response, request: Request, token: str) -> None:
    response.set_cookie(
        COOKIE_NAME,
        token,
        httponly=True,
        secure=_cookie_secure(request),
        samesite="lax",
        path="/",
        max_age=SESSION_DAYS * 24 * 60 * 60,
    )


def clear_session_cookie(response: Response, request: Request) -> None:
    response.delete_cookie(
        COOKIE_NAME,
        path="/",
        httponly=True,
        samesite="lax",
        secure=_cookie_secure(request),
    )


def _raw_cookie(request: Request) -> str | None:
    return request.cookies.get(COOKIE_NAME)


@router.post("/signup")
async def register(
    body: Credentials,
    request: Request,
    response: Response,
    svc: AuthService = Depends(auth_service),
) -> dict[str, str]:
    username, token = await svc.register(body.username, body.password)
    await svc.logout(_raw_cookie(request))
    set_session_cookie(response, request, token)
    return {"username": username}


@router.post("/signin")
async def login(
    body: Credentials,
    request: Request,
    response: Response,
    svc: AuthService = Depends(auth_service),
) -> dict[str, str]:
    username, token = await svc.login(body.username, body.password)
    await svc.logout(_raw_cookie(request))
    set_session_cookie(response, request, token)
    return {"username": username}


@router.post("/signout", status_code=204)
async def logout(
    request: Request,
    response: Response,
    svc: AuthService = Depends(auth_service),
) -> None:
    await svc.logout(_raw_cookie(request))
    clear_session_cookie(response, request)


@router.get("/me")
async def me(
    request: Request,
    svc: AuthService = Depends(auth_service),
) -> dict[str, str]:
    if request.app.state.auth.mode == "session":
        return {"username": await svc.me(_raw_cookie(request))}
    return {"username": (await current_user(request)).name}
