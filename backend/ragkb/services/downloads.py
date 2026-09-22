"""Выдача оригинала документа: проверки реестра, разрешения и пути.

Оригинал отдаётся только по записи реестра: имя файла из запроса, ссылки или
аргументов модели не превращается в путь. Каталог корпуса открывается один
раз, а имя проходится по компонентам относительно его дескриптора без перехода
по симлинкам, поэтому запись в реестре не уводит чтение за пределы каталога.

Разрешение `download_allowed` управляет только выдачей файла: поиск, ответы и
цитаты по закрытому документу работают как раньше.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import stat as stat_module
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

from ragkb.core.answer_events import ToolResult, attachment_result, not_available_result
from ragkb.core.errors import InvalidRequest, NotFound, RagkbError
from ragkb.domain.entities import CorpusDocument
from ragkb.domain.ports import DocumentRegistry

log = logging.getLogger("ragkb")

_NO_REGISTRY = (
    "Реестр документов не подключён: задайте RAGKB_DATABASE_URL. "
    "Выдача оригинала возможна только для зарегистрированных документов."
)

# Один текст на все причины отказа: ответ не должен рассказывать, существует
# ли запись, включено ли разрешение и лежит ли файл на диске.
_NOT_AVAILABLE = "Документ недоступен для скачивания"

_MEDIA_TYPES = {
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".md": "text/markdown",
    ".markdown": "text/markdown",
    ".txt": "text/plain",
    ".html": "text/html",
    ".htm": "text/html",
}

UNKNOWN_MEDIA_TYPE = "application/octet-stream"

# Размер порции при отдаче файла: он не читается целиком в память.
CHUNK_SIZE = 64 * 1024


@dataclass(frozen=True)
class DownloadDescriptor:
    """Проверенный оригинал. Путь наружу не сериализуется.

    `handle` — дескриптор уже проверенного файла. Отдавать файл повторным
    открытием по имени нельзя: между проверкой и открытием имя может стать
    симлинком. Закрывает дескриптор тот, кто получил описание.
    """

    document_id: str
    filename: str
    path: Path
    media_type: str
    size: int
    handle: BinaryIO

    def close(self) -> None:
        """Закрывает дескриптор. Повторный вызов безопасен."""
        if not self.handle.closed:
            self.handle.close()


class DownloadsService:
    """Выдача оригинала и разрешение на неё."""

    def __init__(self, docs_dir: Path, registry: DocumentRegistry | None = None) -> None:
        self._docs_dir = Path(docs_dir)
        self._registry = registry

    @property
    def registry_enabled(self) -> bool:
        return self._registry is not None

    async def resolve(self, document_id: str) -> DownloadDescriptor:
        """Проверяет запись, разрешение и файл; открывает файл без симлинков.

        Вызывается на каждом обращении: разрешение читается из реестра, а не
        из метаданных векторов, поэтому его отзыв действует сразу и без
        переиндексации.
        """
        if self._registry is None:
            raise NotFound(_NO_REGISTRY)
        document = await self._registry.get_by_id(document_id or "")
        if document is None or not document.download_allowed:
            raise NotFound(_NOT_AVAILABLE)
        if not document.sha256:
            # Связать разрешение с конкретными байтами нечем: запись без хэша
            # не выдаётся. Отдавать «то, что лежит по имени» значило бы
            # обойти проверку — такой документ нужно загрузить заново.
            log.warning(
                "выдача оригинала: документ %s без хэша — выдача закрыта",
                document.document_id,
            )
            raise NotFound(_NOT_AVAILABLE)
        try:
            handle, size = _open_document(self._docs_dir, document.name)
        except (OSError, ValueError) as exc:
            # Файл пропал, оказался каталогом или уводит по симлинку — для
            # посетителя это тот же отказ, что и выключенное разрешение.
            raise NotFound(_NOT_AVAILABLE) from exc
        try:
            # Сверяем содержимое уже открытого файла с записью реестра. Имя на
            # диске могло смениться между чтением записи и открытием, а
            # `os.replace` не меняет байты у уже открытого inode: совпадение
            # хэша значит, что выдаются именно те байты, вместе с которыми было
            # прочитано разрешение. Чтение порциями уходит с цикла событий.
            digest = await asyncio.to_thread(_hash_and_rewind, handle)
        except OSError as exc:
            handle.close()
            raise NotFound(_NOT_AVAILABLE) from exc
        except BaseException:
            handle.close()
            raise
        if digest != document.sha256:
            handle.close()
            log.warning(
                "выдача оригинала: содержимое документа %s не совпало с записью",
                document.document_id,
            )
            raise NotFound(_NOT_AVAILABLE)
        return DownloadDescriptor(
            document_id=document.document_id,
            filename=Path(document.name).name,
            path=self._docs_dir / document.name,
            media_type=media_type_for(document.name),
            size=size,
            handle=handle,
        )

    async def set_permission(
        self, document_id: str, allowed: bool
    ) -> tuple[bool, CorpusDocument]:
        """Меняет разрешение. Возвращает прежнее значение и сохранённую запись."""
        if self._registry is None:
            raise InvalidRequest(_NO_REGISTRY)
        result = await self._registry.set_download_allowed(document_id or "", allowed)
        if result is None:
            raise NotFound("Документ не найден в реестре корпуса")
        return result

    async def tool_attachment(self, document_id: str) -> ToolResult:
        """Результат инструмента: описание файла или структурированный отказ.

        Проверки те же, что у выдачи: запись в реестре, разрешение, безопасное
        открытие файла без симлинков. Дескриптор закрывается сразу — инструменту
        нужны только имя, размер и тип, а байты отдаёт отдельный маршрут
        скачивания. Отказ не обрывает полезный текстовый ответ: модель получает
        код `not_available` и продолжает отвечать.
        """
        try:
            descriptor = await self.resolve(document_id)
        except RagkbError:
            return not_available_result()
        try:
            return attachment_result(
                document_id=descriptor.document_id,
                filename=descriptor.filename,
                media_type=descriptor.media_type,
                size=descriptor.size,
            )
        finally:
            descriptor.close()


def media_type_for(name: str) -> str:
    """Тип содержимого по расширению; неизвестное — двоичный поток."""
    return _MEDIA_TYPES.get(Path(name).suffix.lower(), UNKNOWN_MEDIA_TYPE)


def _hash_and_rewind(handle: BinaryIO) -> str:
    """Считает SHA-256 открытого файла порциями и возвращает чтение в начало.

    Файл не читается целиком в память, поэтому проверка годится и для
    предельного размера загрузки.
    """
    digest = hashlib.sha256()
    while True:
        chunk = handle.read(CHUNK_SIZE)
        if not chunk:
            break
        digest.update(chunk)
    handle.seek(0)
    return digest.hexdigest()


def _relative_parts(name: str) -> list[str]:
    """Разбирает имя из реестра на компоненты пути или отказывает.

    Абсолютные имена, `..`, NUL и пустые компоненты запрещены: имя приходит из
    реестра, но проверка нужна и здесь — запись могла появиться раньше, чем
    это правило.
    """
    if not name or "\x00" in name or name.startswith(("/", "\\")):
        raise ValueError("Недопустимое имя документа")
    parts = [part for part in name.replace("\\", "/").split("/") if part not in ("", ".")]
    if not parts or any(part == ".." for part in parts):
        raise ValueError("Недопустимое имя документа")
    return parts


def _open_document(root: Path, name: str) -> tuple[BinaryIO, int]:
    """Открывает файл документа, не проходя по симлинкам.

    Каталог корпуса открывается один раз, а компоненты имени проходятся
    относительно его дескриптора с `O_NOFOLLOW`: ни конечный, ни
    промежуточный симлинк не уводит чтение за пределы каталога. Файл
    возвращается уже открытым — повторное открытие по имени снова сделало бы
    проверку бессмысленной.

    Конечный компонент открывается ещё и с `O_NONBLOCK`: имя из реестра может
    указывать на FIFO, а обычное открытие такого файла ждёт писателя и
    остановило бы весь цикл событий до появления данных. Неблокирующее
    открытие возвращается сразу, а `S_ISREG` ниже отсекает всё, кроме обычных
    файлов. На обычных файлах флаг ни на что не влияет.
    """
    parts = _relative_parts(name)
    directory = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
    try:
        for part in parts[:-1]:
            following = os.open(
                part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory
            )
            os.close(directory)
            directory = following
        descriptor = os.open(
            parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory
        )
    finally:
        os.close(directory)
    try:
        file_stat = os.fstat(descriptor)
        if not stat_module.S_ISREG(file_stat.st_mode):
            raise OSError("документ не является обычным файлом")
    except OSError:
        os.close(descriptor)
        raise
    return os.fdopen(descriptor, "rb"), file_stat.st_size
