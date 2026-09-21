"""Порты реестра, каталога и телеметрии."""
from typing import Any, Protocol
from ragkb.domain.entities import ORIGIN_UI, CorpusDocument


class DocumentRegistry(Protocol):
    """Реестр документов корпуса: что и кем принято в базу знаний.

    Индекс собирается по реестру, поэтому «нет записи» значит «файл лежит
    в каталоге мимо интерфейса и в ответы не попадёт», пока его не примут.
    """

    async def names(self) -> set[str]:
        """Имена (пути относительно каталога корпуса) принятых документов."""
    async def list_all(self) -> list[CorpusDocument]: ...
    async def record(
        self,
        name: str,
        *,
        origin: str = ORIGIN_UI,
        uploaded_by: str = "",
        size: int = 0,
        sha256: str = "",
    ) -> None:
        """Заводит документ или обновляет сведения о нём."""
    async def forget(self, name: str) -> bool:
        """Убирает документ из реестра. True — запись была."""


class ModelCatalog(Protocol):
    def list(self) -> list: ...
    def resolve(self, requested: str | None) -> str: ...


# --- Телеметрия ---


class EventSink(Protocol):
    def emit(self, payload: dict[str, Any]) -> None: ...
