"""Чистые сущности корпуса."""
from dataclasses import dataclass
from typing import Any

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
    origin: str = ORIGIN_UI
    uploaded_by: str = ""
    uploaded_at: str = ""
    size: int = 0
    sha256: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "origin": self.origin,
            "uploaded_by": self.uploaded_by,
            "uploaded_at": self.uploaded_at,
            "size": self.size,
            "sha256": self.sha256,
        }
