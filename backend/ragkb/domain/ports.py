"""Порты реестра, каталога и телеметрии."""
from typing import Any, Protocol
from ragkb.domain.entities import ORIGIN_UI, CorpusDocument, RecordOutcome


class DocumentRegistry(Protocol):
    """Реестр документов корпуса: что и кем принято в базу знаний.

    Индекс собирается по реестру, поэтому «нет записи» значит «файл лежит
    в каталоге мимо интерфейса и в ответы не попадёт», пока его не примут.
    """

    async def names(self) -> set[str]:
        """Имена (пути относительно каталога корпуса) принятых документов."""
    async def index_names(self) -> set[str]:
        """Имена документов, участвующих в поиске.

        Индекс собирается только по ним: документ с выключенным
        `index_enabled` остаётся в корпусе и доступен для скачивания, но его
        фрагменты в ответы не попадают.
        """
    async def list_all(self) -> list[CorpusDocument]: ...
    async def get_by_id(self, document_id: str) -> CorpusDocument | None:
        """Запись по идентификатору. None — такого документа в реестре нет."""
    async def record(
        self,
        name: str,
        *,
        origin: str = ORIGIN_UI,
        uploaded_by: str = "",
        size: int = 0,
        sha256: str = "",
        download_allowed: bool = False,
        index_enabled: bool = True,
    ) -> RecordOutcome:
        """Заводит документ или обновляет сведения о нём.

        Замена существующего имени сохраняет `document_id`, но не прежнее
        разрешение: `download_allowed` берётся из этого вызова. Прежнее
        значение и признак создания возвращаются вместе с записью — из неё же,
        а не из отдельного чтения до неё.
        """
    async def set_download_allowed(
        self, document_id: str, allowed: bool
    ) -> tuple[bool, CorpusDocument] | None:
        """Меняет разрешение на выдачу оригинала.

        Возвращает прежнее значение вместе с сохранённой записью — новое
        значение читается в той же транзакции, а не отдельным чтением до
        записи. None — документа с таким идентификатором нет.
        """
    async def set_index_enabled(
        self, document_id: str, enabled: bool
    ) -> tuple[bool, CorpusDocument] | None:
        """Включает или выключает участие документа в поиске.

        Возвращает прежнее значение и сохранённую запись: новый флаг
        применяется при следующей сборке индекса, а прежнее значение нужно
        журналу — так же, как у разрешения на скачивание.
        """
    async def forget(self, name: str) -> bool:
        """Убирает документ из реестра. True — запись была."""


class ModelCatalog(Protocol):
    def list(self) -> list: ...
    def resolve(self, requested: str | None) -> str: ...




class EventSink(Protocol):
    def emit(self, payload: dict[str, Any]) -> None: ...
