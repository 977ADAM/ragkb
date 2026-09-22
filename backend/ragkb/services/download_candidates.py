"""Кандидаты на скачивание для текущего вопроса.

Кандидаты — подсказка модели, а не разрешение. Набор собирается из двух
источников: названий, упомянутых в вопросе (прямая просьба «пришли требования
к AdSmart Multi»), и документов, к которым привязаны найденные фрагменты.
Поэтому PDF попадает в набор, даже если ответ построен на закрытом DOCX.

Разрешение всегда берётся из реестра, а пути в набор не попадают вовсе: модель
видит идентификаторы и имена, а какой файл отдавать, решает сервер.
"""
from __future__ import annotations

import unicodedata
from collections.abc import Iterable, Sequence
from pathlib import Path

from ragkb.core.answer_events import (
    DownloadResolver,
    ToolCandidate,
    ToolResult,
    not_available_result,
)
from ragkb.core.retrieval import Hit
from ragkb.domain.entities import CorpusDocument
from ragkb.domain.ports import DocumentRegistry
from ragkb.services.downloads import DownloadsService

# Больше двадцати похожих названий — это уже не выбор, а угадывание: пусть
# модель попросит уточнить, вместо того чтобы получить случайную часть списка.
CANDIDATE_LIMIT = 20

# Служебные слова вопроса и названия формата: сами по себе они ничего не
# называют, и совпадение по ним превратило бы набор в свалку.
_STOP_WORDS = frozenset(
    {
        "а", "без", "бы", "в", "вам", "вас", "все", "вы", "да", "дай", "дайте",
        "для", "до", "документ", "документы", "doc", "docx", "если", "есть",
        "ещё", "еще", "же", "за", "и", "из", "или", "им", "их", "к", "как",
        "какие", "какой", "ко", "ли", "мне", "можно", "на", "над", "нам",
        "нас", "не", "него", "нее", "нет", "ни", "но", "нужен", "нужна",
        "нужно", "нужны", "о", "об", "он", "она", "они", "оригинал",
        "оригиналы", "от", "пдф", "по", "под", "пожалуйста", "пришли",
        "пришлите", "про", "с", "сам", "свой", "себе", "скинь", "скиньте",
        "со", "так", "там", "те", "тем", "то", "требование", "требования",
        "требований", "у", "файл", "файлы", "хочу", "что", "чтобы", "это",
        "этот", "pdf", "txt", "md", "markdown", "htm",
    }
)


def match_names(question: str, names: Sequence[str]) -> list[str]:
    """Названия документов, названные в вопросе.

    Точное название получает приоритет: если документ назван целиком, похожие
    варианты (HTML5 и Mobile HTML5, MediaText и MediaText Premium) в подборку
    не попадают — иначе модель выбирала бы файл наугад. Если точного названия
    нет, работает совпадение по содержательным словам.
    """
    asked = _normalize(question)
    if not asked:
        return []
    exact = _exact_matches(asked, names)
    if exact:
        return exact

    tokens = _content_tokens(asked)
    if not tokens:
        return []
    return [name for name in names if tokens & _content_tokens(_normalize(name))]


async def prepare_candidates(
    question: str,
    hits: Sequence[Hit],
    registry: DocumentRegistry | None,
    docs_dir: str | Path,
) -> list[ToolCandidate]:
    """Собирает набор кандидатов для одного вопроса.

    Реестр — единственный источник документов: без него кандидатов нет, и это
    никак не мешает обычному ответу. Закрытые документы в набор попадают с
    `download_allowed=False`: модель должна видеть, что оригинал недоступен.
    """
    if registry is None:
        return []
    documents = await registry.list_all()
    by_name = {document.name: document for document in documents}
    named = match_names(question, sorted(by_name))
    if len(named) > CANDIDATE_LIMIT:
        # Слишком широкая подборка: любая её часть была бы случайной.
        return []

    candidates: dict[str, ToolCandidate] = {}
    for name in named:
        document = by_name[name]
        candidates[document.document_id] = _candidate(document)
    for hit in hits:
        document = _document_for_hit(hit, by_name, docs_dir)
        if document is not None:
            candidates.setdefault(document.document_id, _candidate(document))
    return list(candidates.values())


def download_resolver(
    downloads: DownloadsService, candidates: Iterable[ToolCandidate]
) -> DownloadResolver:
    """Обработчик инструмента для одного вопроса.

    Набор фиксируется на время вопроса: идентификатор вне него получает отказ,
    даже если документ разрешён в реестре. Разрешение при этом перечитывается
    на каждом вызове, поэтому отзыв после подготовки кандидатов действует сразу.
    """
    allowed = {
        candidate["document_id"]
        for candidate in candidates
        if candidate["download_allowed"]
    }

    async def resolve(document_id: str) -> ToolResult:
        if document_id not in allowed:
            return not_available_result()
        return await downloads.tool_attachment(document_id)

    return resolve


def _candidate(document: CorpusDocument) -> ToolCandidate:
    return ToolCandidate(
        document_id=document.document_id,
        filename=Path(document.name).name,
        download_allowed=bool(document.download_allowed),
    )


def _document_for_hit(
    hit: Hit, by_name: dict[str, CorpusDocument], docs_dir: str | Path
) -> CorpusDocument | None:
    """Документ реестра, к которому привязан найденный фрагмент.

    Источник фрагмента — путь внутри каталога корпуса, и запись ищется по нему,
    а не по имени файла: чужой путь с тем же именем иначе выдал бы за корпусный
    документ что угодно.
    """
    source = str(hit.document.metadata.get("source") or "")
    if not source:
        return None
    root = Path(docs_dir).expanduser().resolve()
    try:
        path = Path(source).resolve()
    except OSError:
        return None
    if path != root and root not in path.parents:
        return None
    return by_name.get(path.relative_to(root).as_posix())


def _normalize(text: str) -> str:
    """Приводит текст к сравнимому виду: регистр, форма символов, разделители."""
    decomposed = unicodedata.normalize("NFKC", str(text)).casefold()
    cleaned = "".join(char if char.isalnum() else " " for char in decomposed)
    return " ".join(cleaned.split())


def _stem(name: str) -> str:
    """Название без расширения: «.pdf» не должно мешать совпадению слов.

    Нормализация заменяет точку разделителем, поэтому расширение снимается у
    исходного имени, а не у приведённого.
    """
    return _normalize(Path(name).stem)


def _mentions(asked: str, name: str) -> bool:
    stem = _stem(name)
    return _contains_words(asked, stem) or _contains_words(asked, _normalize(name))


def _contains_words(haystack: str, needle: str) -> bool:
    if not needle:
        return False
    return f" {needle} " in f" {haystack} "


def _exact_matches(asked: str, names: Sequence[str]) -> list[str]:
    matched = [name for name in names if _mentions(asked, name)]
    if not matched:
        return []
    # Короткое название, целиком входящее в другое совпадение, — это тот же
    # документ с уточнением: «FAQ» и «FAQ 2026».
    def covered(name: str) -> bool:
        stem = _stem(name)
        return any(other != name and stem and stem in _stem(other) for other in matched)

    return [name for name in matched if not covered(name)]


def _content_tokens(normalized: str) -> set[str]:
    return {
        token
        for token in normalized.split()
        if len(token) > 1 and token not in _STOP_WORDS
    }
