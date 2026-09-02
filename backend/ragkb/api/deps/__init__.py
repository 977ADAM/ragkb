"""HTTP Depends: идентификация и фабрики сервисов для роутов."""
from ragkb.api.deps.auth import (
    AuthSvc,
    current_user,
    get_auth_service,
    optional_user,
    require_admin,
)

__all__ = [
    "AuthSvc",
    "current_user",
    "get_auth_service",
    "optional_user",
    "require_admin",
]
