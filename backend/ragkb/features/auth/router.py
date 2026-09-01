from __future__ import annotations

from fastapi import APIRouter, Depends, Request, Response

from ragkb.features.auth.schemas import Credentials
from ragkb.features.auth.service import AuthService
from ragkb.features.auth.sqlite import COOKIE_NAME, SESSION_DAYS
from ragkb.platform.auth import current_user
from ragkb.platform.deps import auth_service

router = APIRouter()


def set_session_cookie(response: Response, request: Request, token: str) -> None:
    forwarded = request.headers.get("x-forwarded-proto", "").split(",")[0].strip()
    secure = request.url.scheme == "https" or forwarded == "https"
    response.set_cookie(
        COOKIE_NAME,
        token,
        httponly=True,
        secure=secure,
        samesite="lax",
        path="/",
        max_age=SESSION_DAYS * 24 * 60 * 60,
    )


def _raw_cookie(request: Request) -> str | None:
    return request.cookies.get(COOKIE_NAME)


@router.post("/auth/register")
def register(
    body: Credentials,
    request: Request,
    response: Response,
    svc: AuthService = Depends(auth_service),
) -> dict[str, str]:
    svc.logout(_raw_cookie(request))
    username, token = svc.register(body.username, body.password)
    set_session_cookie(response, request, token)
    return {"username": username}


@router.post("/auth/login")
def login(
    body: Credentials,
    request: Request,
    response: Response,
    svc: AuthService = Depends(auth_service),
) -> dict[str, str]:
    svc.logout(_raw_cookie(request))
    username, token = svc.login(body.username, body.password)
    set_session_cookie(response, request, token)
    return {"username": username}


@router.post("/auth/logout", status_code=204)
def logout(
    request: Request,
    response: Response,
    svc: AuthService = Depends(auth_service),
) -> None:
    svc.logout(_raw_cookie(request))
    response.delete_cookie(COOKIE_NAME, path="/")


@router.get("/auth/me")
def me(
    request: Request,
    svc: AuthService = Depends(auth_service),
) -> dict[str, str]:
    if request.app.state.auth.mode == "session":
        return {"username": svc.me(_raw_cookie(request))}
    return {"username": current_user(request).name}
