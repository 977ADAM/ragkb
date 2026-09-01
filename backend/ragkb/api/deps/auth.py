"""HTTP Depends: фабрика AuthService."""
from typing import Annotated

from fastapi import Depends, Request, Response

from ragkb.platform.container import Container
from ragkb.services.auth import COOKIE_NAME, SESSION_DAYS, AuthService


async def get_current_user():
    """Возвращает текущего пользователя, если он авторизован, иначе None."""
    from ragkb.api.deps import AuthSvc
    from ragkb.platform.auth import current_user

    async def _get_current_user(
        request: Request,
        svc: AuthSvc,
    ):
        token = request.cookies.get(COOKIE_NAME)
        if not token:
            return None
        return await current_user(svc, token)

    return _get_current_user    
    
    

def get_auth_service(request: Request) -> AuthService:
    c: Container = request.app.state.container
    c._ensure_postgres()
    if c.accounts is None:
        raise RuntimeError("Хранилище учёток недоступно: Postgres не подключён")
    return AuthService(c.accounts)


AuthSvc = Annotated[AuthService, Depends(get_auth_service)]


def cookie_secure(request: Request) -> bool:
    forwarded = request.headers.get("x-forwarded-proto", "").split(",")[0].strip()
    return request.url.scheme == "https" or forwarded == "https"


def set_session_cookie(response: Response, request: Request, token: str) -> None:
    response.set_cookie(
        COOKIE_NAME,
        token,
        httponly=True,
        secure=cookie_secure(request),
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
        secure=cookie_secure(request),
    )


def raw_cookie(request: Request) -> str | None:
    return request.cookies.get(COOKIE_NAME)
