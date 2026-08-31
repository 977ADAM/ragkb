"""Нарезка документа на чанки.

Ключевая идея: чанк — это не «N символов подряд», а связный фрагмент,
который несёт с собой путь заголовков (breadcrumb). Заголовок в тексте чанка
резко улучшает и BM25, и плотный поиск: запрос «срок оплаты отпуска» найдёт
абзац, где слово «отпуск» встречается только в заголовке раздела.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from typing import Any

from .config import ChunkConfig
from .loaders import Block, Document


@dataclass
class Chunk:
    chunk_id: str
    doc_id: str
    text: str            # текст для генерации ответа (то, что видит LLM)
    embed_text: str      # текст для индексации (с breadcrumb-заголовками)
    source: str          # путь к файлу
    title: str           # заголовок документа
    section: str         # путь заголовков, например «Регламент > Отпуска > Оплата»
    page: int | None
    position: int        # порядковый номер чанка в документе
    meta: dict[str, Any] = field(default_factory=dict)

    def citation(self) -> str:
        # Заголовок документа часто совпадает с корневым заголовком раздела —
        # не дублируем его в ссылке.
        section = self.section
        if section == self.title:
            section = ""
        elif section.startswith(f"{self.title} > "):
            section = section[len(self.title) + 3 :]
        parts = [self.title, section]
        if self.page:
            parts.append(f"с. {self.page}")
        return " / ".join(p for p in parts if p)


def chunk_document(doc: Document, cfg: ChunkConfig) -> list[Chunk]:
    """Делит документ на чанки, отслеживая иерархию заголовков."""
    chunks: list[Chunk] = []
    heading_stack: list[tuple[int, str]] = []
    buffer: list[Block] = []
    position = 0

    def buffer_len() -> int:
        return sum(len(b.text) + 1 for b in buffer)

    def flush() -> None:
        nonlocal position, buffer
        if not buffer:
            return
        text = "\n".join(b.text for b in buffer).strip()
        if not text:
            buffer = []
            return
        section = " > ".join(h for _, h in heading_stack)
        page = next((b.page for b in buffer if b.page), None)
        chunks.append(_make_chunk(doc, text, section, page, position))
        position += 1
        # Оверлап: тащим хвост предыдущего чанка в следующий, чтобы не
        # разрывать мысль ровно по границе.
        buffer = _tail_blocks(buffer, cfg.overlap) if cfg.overlap > 0 else []

    for block in doc.blocks:
        if block.kind == "heading" and cfg.respect_structure:
            flush()
            buffer = []  # после заголовка оверлап не нужен — начинается новая тема
            level = block.level or 1
            while heading_stack and heading_stack[-1][0] >= level:
                heading_stack.pop()
            heading_stack.append((level, block.text))
            continue

        # Абзац длиннее лимита режем по предложениям.
        if len(block.text) > cfg.size:
            flush()
            for piece in _split_long(block.text, cfg.size, cfg.overlap):
                buffer = [Block(text=piece, kind=block.kind, page=block.page)]
                flush()
                buffer = []
            continue

        buffer.append(block)
        if buffer_len() >= cfg.size:
            flush()

    flush()
    return _merge_tiny(chunks, cfg.min_size)


def chunk_documents(docs: list[Document], cfg: ChunkConfig) -> list[Chunk]:
    out: list[Chunk] = []
    for doc in docs:
        out.extend(chunk_document(doc, cfg))
    return out


# ------------------------------------------------------------------- внутреннее

def _make_chunk(doc: Document, text: str, section: str, page: int | None, position: int) -> Chunk:
    # embed_text отличается от text: в него добавлен контекст заголовков.
    parts = [doc.title]
    if section and section != doc.title and not section.startswith(f"{doc.title} > "):
        parts.append(section)
    elif section.startswith(f"{doc.title} > "):
        parts.append(section[len(doc.title) + 3 :])
    header = " > ".join(p for p in parts if p)
    embed_text = f"{header}\n{text}" if header else text
    raw_id = f"{doc.doc_id}:{position}:{hashlib.sha1(text.encode()).hexdigest()[:8]}"
    return Chunk(
        chunk_id=raw_id,
        doc_id=doc.doc_id,
        text=text,
        embed_text=embed_text,
        source=doc.path,
        title=doc.title,
        section=section,
        page=page,
        position=position,
        meta=dict(doc.meta),
    )


def _tail_blocks(blocks: list[Block], overlap: int) -> list[Block]:
    """Возвращает последние блоки суммарной длиной ≈ overlap."""
    tail: list[Block] = []
    total = 0
    for block in reversed(blocks):
        if total >= overlap:
            break
        tail.insert(0, block)
        total += len(block.text)
    # Не переносим целиком, если это весь чанк — иначе получим бесконечный цикл.
    return tail if len(tail) < len(blocks) else tail[-1:] if len(blocks) > 1 else []


_SENTENCE_RE = re.compile(r"(?<=[.!?…])\s+(?=[А-ЯЁA-Z«\"(\d])")


def _split_long(text: str, size: int, overlap: int) -> list[str]:
    """Режет длинный абзац по границам предложений, с оверлапом."""
    sentences = [s.strip() for s in _SENTENCE_RE.split(text) if s.strip()] or [text]
    pieces: list[str] = []
    current: list[str] = []
    length = 0
    for sent in sentences:
        # Одно предложение длиннее лимита — режем жёстко по символам.
        if len(sent) > size:
            if current:
                pieces.append(" ".join(current))
                current, length = [], 0
            for i in range(0, len(sent), size - overlap if size > overlap else size):
                pieces.append(sent[i : i + size])
            continue
        if length + len(sent) > size and current:
            pieces.append(" ".join(current))
            current, length = _overlap_tail(current, overlap)
        current.append(sent)
        length += len(sent) + 1
    if current:
        pieces.append(" ".join(current))
    return [p for p in pieces if p.strip()]


def _overlap_tail(sentences: list[str], overlap: int) -> tuple[list[str], int]:
    tail: list[str] = []
    total = 0
    for sent in reversed(sentences):
        if total >= overlap:
            break
        tail.insert(0, sent)
        total += len(sent) + 1
    return tail, total


def _merge_tiny(chunks: list[Chunk], min_size: int) -> list[Chunk]:
    """Склеивает слишком короткие чанки с соседями того же документа."""
    if not chunks:
        return chunks
    merged: list[Chunk] = []
    for chunk in chunks:
        # Склеиваем только внутри одного раздела и одной страницы: иначе
        # чанк получит ссылку на источник, которому принадлежит лишь его часть.
        if (
            merged
            and len(chunk.text) < min_size
            and merged[-1].doc_id == chunk.doc_id
            and merged[-1].section == chunk.section
            and merged[-1].page == chunk.page
            and len(merged[-1].text) + len(chunk.text) < min_size * 8
        ):
            prev = merged[-1]
            prev.text = f"{prev.text}\n{chunk.text}"
            prev.embed_text = f"{prev.embed_text}\n{chunk.text}"
            continue
        merged.append(chunk)
    return merged
