from __future__ import annotations

from typing import Protocol, Optional
from entities.auth.auth import User, Session


class UserRepository(Protocol):
    """Интерфейс репозитория пользователей."""
    
    async def add(self, user: User) -> User:
        """Создать пользователя."""
        ...
    
    async def get_by_id(self, user_id: int) -> Optional[User]:
        """Получить пользователя по ID."""
        ...
    
    async def get_by_username(self, username: str) -> Optional[User]:
        """Получить пользователя по имени."""
        ...
    
    async def get_by_email(self, email: str) -> Optional[User]:
        """Получить пользователя по email."""
        ...
    
    async def update(self, user: User) -> User:
        """Обновить пользователя."""
        ...
    
    async def delete(self, user_id: int) -> None:
        """Удалить пользователя."""
        ...


class SessionRepository(Protocol):
    """Интерфейс репозитория сессий."""
    
    async def add(self, session: Session) -> Session:
        """Создать сессию."""
        ...
    
    async def get(self, session_id: str) -> Optional[Session]:
        """Получить сессию по ID."""
        ...
    
    async def delete(self, session_id: str) -> None:
        """Удалить сессию."""
        ...
    
    async def delete_all_for_user(self, user_id: int) -> None:
        """Удалить все сессии пользователя."""
        ...
    
    async def clean_expired(self) -> int:
        """Удалить истекшие сессии. Возвращает количество удаленных."""
        ...


class PasswordHasher(Protocol):
    """Интерфейс для хеширования паролей."""
    
    def hash(self, password: str) -> str:
        """Захешировать пароль."""
        ...
    
    def verify(self, password: str, hash: str) -> bool:
        """Проверить пароль."""
        ...


class TokenService(Protocol):
    """Интерфейс для работы с токенами."""
    
    def create_session_token(self, user_id: int) -> str:
        """Создать токен для сессии."""
        ...
    
    def verify_session_token(self, token: str) -> Optional[int]:
        """Проверить токен и вернуть user_id."""
        ...