"""Документы в терминах LangChain: секции, чанки, идентификаторы, цитаты.

Единица обмена с LangChain — `Document` (page_content + metadata). Наш корпус
превращается в него в два шага:

1. блоки файла собираются в секции по иерархии заголовков — так чанк знает
   свой раздел и не смешивает темы;
2. секции режет `RecursiveCharacterTextSplitter` (langchain-text-splitters) по
   абзацам и границам предложений.

Путь заголовков («breadcrumb») хранится в metadata и дописывается в начало
page_content каждой части: заголовок в тексте резко улучшает и лексический,
и плотный поиск — запрос «срок оплаты отпуска» находит абзац, где слово
«отпуск» есть только в названии раздела. Для показа пользователю
`document_text` отрезает breadcrumb обратно.
"""
from __future__ import annotations

import hashlib
from collections.abc import Iterable, Sequence
from typing import Any

from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

from .config import Settings
from .loaders import Block, LoadedDocument

BREADCRUMB = "breadcrumb"
_SECTION_SEPARATOR = " > "


def section_documents(loaded: LoadedDocument) -> list[Document]:
    """Собирает блоки файла в документы-секции по иерархии заголовков."""
    sections: list[Document] = []
    heading_stack: list[tuple[int, str]] = []
    buffer: list[Block] = []
    position = 0

    def flush() -> None:
        nonlocal buffer, position
        if not buffer:
            return
        text = "\n".join(block.text for block in buffer).strip()
        page = next((block.page for block in buffer if block.page), None)
        buffer = []
        if not text:
            return
        sections.append(
            Document(
                page_content=text,
                metadata=_metadata(loaded, heading_stack, page, position),
            )
        )
        position += 1

    for block in loaded.blocks:
        if block.kind == "heading":
            flush()
            level = block.level or 1
            while heading_stack and heading_stack[-1][0] >= level:
                heading_stack.pop()
            heading_stack.append((level, block.text))
            continue
        buffer.append(block)
    flush()

    if not sections:
        # Документ без единого заголовка: одна секция из всего текста.
        text = "\n".join(block.text for block in loaded.blocks).strip()
        if text:
            sections.append(
                Document(page_content=text, metadata=_metadata(loaded, [], None, 0))
            )
    return sections


def split_documents(
    documents: Sequence[Document], cfg: Settings.ChunkConfig
) -> list[Document]:
    """Режет секции на чанки, сохраняя метаданные и дописывая breadcrumb."""
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=cfg.size,
        chunk_overlap=cfg.overlap,
        # Абзац → конец предложения → строка → пробел: чанк рвётся по смыслу,
        # а не посередине слова.
        separators=[r"\n{2,}", r"(?<=[.!?…])\s+", r"\n", r"\s+", ""],
        is_separator_regex=True,
        keep_separator="end",
    )
    parts: list[Document] = []
    for document in documents:
        pieces = splitter.split_documents([document])
        breadcrumb = str(document.metadata.get(BREADCRUMB) or "")
        for piece in pieces:
            text = piece.page_content.strip()
            if not text:
                continue
            piece.metadata[BREADCRUMB] = breadcrumb
            # Breadcrumb добавляется после нарезки: иначе он достался бы
            # только первой части длинной секции.
            piece.page_content = f"{breadcrumb}\n{text}" if breadcrumb else text
            parts.append(piece)

    counters: dict[str, int] = {}
    for index, piece in enumerate(parts):
        doc_id = str(piece.metadata.get("doc_id") or "")
        position = counters.get(doc_id, 0)
        counters[doc_id] = position + 1
        piece.metadata["position"] = position
        piece.metadata["chunk_id"] = make_chunk_id(piece, index)
    return parts


def make_chunk_id(document: Document, index: int = 0) -> str:
    """Идентификатор чанка: документ, порядок и хэш содержимого."""
    doc_id = str(document.metadata.get("doc_id") or "doc")
    digest = hashlib.sha1(document.page_content.encode("utf-8")).hexdigest()[:8]
    position = document.metadata.get("position")
    return f"{doc_id}:{position if position is not None else index}:{digest}"


def with_scalar_metadata(document: Document) -> Document:
    """Приводит метаданные к скалярам: хранилища не принимают None и вложенность."""
    document.metadata = flatten_metadata(document.metadata)
    return document


def flatten_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in metadata.items():
        if value is None:
            continue
        if isinstance(value, (str, int, float, bool)):
            out[key] = value
    return out


def document_text(document: Document) -> str:
    """Текст чанка без breadcrumb — то, что показывается пользователю."""
    breadcrumb = str(document.metadata.get(BREADCRUMB) or "")
    content = document.page_content
    if breadcrumb and content.startswith(breadcrumb):
        return content[len(breadcrumb) :].lstrip("\n")
    return content


def document_section(document: Document) -> str:
    return str(document.metadata.get("section") or "")


def document_page(document: Document) -> int | None:
    page = document.metadata.get("page")
    if isinstance(page, int) and page > 0:
        return page
    return None


def document_citation(document: Document) -> str:
    """Ссылка на источник: заголовок документа, раздел, страница.

    Заголовок документа часто совпадает с корневым заголовком раздела —
    не дублируем его в ссылке.
    """
    title = str(document.metadata.get("title") or "")
    section = document_section(document)
    if section == title:
        section = ""
    elif title and section.startswith(f"{title}{_SECTION_SEPARATOR}"):
        section = section[len(title) + len(_SECTION_SEPARATOR) :]
    parts = [title, section]
    page = document_page(document)
    if page:
        parts.append(f"с. {page}")
    return " / ".join(part for part in parts if part)


def documents_from_payload(
    contents: Iterable[str], metadatas: Iterable[dict[str, Any]], ids: Iterable[str]
) -> list[Document]:
    """Собирает документы из ответа хранилища (get/add) в исходном порядке."""
    out: list[Document] = []
    for content, metadata, chunk_id in zip(contents, metadatas, ids, strict=False):
        out.append(
            Document(
                page_content=content,
                metadata={**(metadata or {}), "chunk_id": chunk_id},
            )
        )
    return out


def _metadata(
    loaded: LoadedDocument, heading_stack: list[tuple[int, str]], page: int | None, position: int
) -> dict[str, Any]:
    section = _SECTION_SEPARATOR.join(heading for _, heading in heading_stack)
    return flatten_metadata(
        {
            "doc_id": loaded.doc_id,
            "source": loaded.path,
            "title": loaded.title,
            "section": section,
            BREADCRUMB: breadcrumb_for(loaded.title, section),
            "page": page or -1,
            "position": position,
            "format": loaded.meta.get("format", ""),
        }
    )


def breadcrumb_for(title: str, section: str) -> str:
    """Заголовок раздела без повтора названия документа."""
    parts = [title]
    if section and section != title:
        if section.startswith(f"{title}{_SECTION_SEPARATOR}"):
            parts.append(section[len(title) + len(_SECTION_SEPARATOR) :])
        else:
            parts.append(section)
    return _SECTION_SEPARATOR.join(part for part in parts if part)
