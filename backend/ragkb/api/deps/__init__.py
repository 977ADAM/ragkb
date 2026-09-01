"""HTTP Depends: фабрики сервисов для роутов."""
from ragkb.api.deps.auth import AuthSvc, get_auth_service

__all__ = ["AuthSvc", "get_auth_service"]
