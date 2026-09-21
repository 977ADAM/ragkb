"""Чистые сущности корпуса."""
from dataclasses import dataclass
from typing import Any

ORIGIN_UI = "ui"
ORIGIN_EXTERNAL = "external"


@dataclass(frozen=True)
class CorpusDocument:
    """Запись реестра документов корпуса.

    Наличие записи — единственный признак принадлежности корпусу: индекс
    собирается по реестру, поэтому файл, положенный в каталог мимо
    интерфейса, в ответы не попадёт, пока его не примут.
    `origin` хранит, как документ появился: для разбирательств «откуда
    взялся этот файл» это важнее, чем одинаковая судьба в индексе.
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
