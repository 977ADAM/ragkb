"""Чистые сущности корпуса."""
from dataclasses import dataclass
from typing import Any, NamedTuple

ORIGIN_UI = "ui"


@dataclass(frozen=True)
class CorpusDocument:
    """Запись реестра документов корпуса.

    Наличие записи — единственный признак принадлежности корпусу: индекс
    собирается по реестру, а реестр наполняется загрузкой через интерфейс.
    Файл, положенный в каталог мимо него, в ответы не попадёт.
    `origin` хранит, как документ появился — на будущее, когда способов
    станет больше одного.
    """

    name: str
    document_id: str
    origin: str = ORIGIN_UI
    uploaded_by: str = ""
    uploaded_at: str = ""
    size: int = 0
    sha256: str = ""
    download_allowed: bool = False
    index_enabled: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "document_id": self.document_id,
            "origin": self.origin,
            "uploaded_by": self.uploaded_by,
            "uploaded_at": self.uploaded_at,
            "size": self.size,
            "sha256": self.sha256,
            "download_allowed": self.download_allowed,
            "index_enabled": self.index_enabled,
        }


class RecordOutcome(NamedTuple):
    """Что дала запись в реестр.

    Прежнее разрешение и признак создания приходят из самой записи: отдельное
    чтение до неё показало бы устаревшее значение, если между чтением и
    записью тот же документ заменил другой запрос.
    """

    created: bool
    previous_download_allowed: bool
    document: CorpusDocument
    previous_index_enabled: bool = True
