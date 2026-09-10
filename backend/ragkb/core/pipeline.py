"""Оркестрация: индексация и вопрос-ответ."""
from __future__ import annotations

import json
import re
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import loaders
from .chunking import chunk_documents
from .config import Settings
from .embeddings import Embedder, TfidfEmbedder, build_embedder
from .llm import LLM, LLMError, build_llm
from .prompts import (
    ANSWER_TEMPLATE,
    CONDENSE_PROMPT,
    QUERY_EXPANSION_PROMPT,
    SYSTEM_PROMPT,
    format_context,
)
from .retrieval import Hit, Retriever, reciprocal_rank_fusion
from .store import BaseStore, create_store, open_store


@dataclass
class Answer:
    question: str
    text: str
    hits: list[Hit]
    used_sources: list[dict[str, Any]] = field(default_factory=list)
    elapsed: float = 0.0
    llm_backend: str = ""
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "question": self.question,
            "answer": self.text,
            "sources": self.used_sources,
            "chunks": [h.to_dict() for h in self.hits],
            "elapsed_sec": round(self.elapsed, 2),
            "llm": self.llm_backend,
            "warnings": self.warnings,
        }


# --------------------------------------------------------------------- индексация

@dataclass
class IndexReport:
    files: int
    chunks: int
    skipped: list[tuple[str, str]]
    elapsed: float
    embedder: str
    store_backend: str = ""
    warnings: list[str] = field(default_factory=list)
    # Файлы, которые лежат в каталоге, но в корпус не приняты: их индексация
    # не касается. Показываем их вызывающему коду — иначе пропажа документов
    # из выдачи выглядела бы необъяснимой.
    excluded: list[str] = field(default_factory=list)


def build_index(
    cfg: Settings,
    *,
    docs_dir: str | Path | None = None,
    progress: Callable[[str], None] | None = None,
    allow: Callable[[str], bool] | None = None,
) -> IndexReport:
    """Полная переиндексация каталога документов.

    `allow` — предикат по имени файла относительно каталога корпуса:
    индексируются только те документы, которые приняты в корпус (реестр
    ведёт прикладной слой). Без предиката берётся всё, что нашлось.
    """
    started = time.time()
    say = progress or (lambda _msg: None)
    source = Path(docs_dir or cfg.docs_dir)

    files, excluded = _accepted_only(loaders.discover(source), source, allow)
    for path in excluded:
        say(f"  × вне корпуса, пропущен {path.name}")
    if not files:
        if excluded:
            raise ValueError(
                f"Ни один файл не принят в корпус: {len(excluded)} файл(ов) лежат "
                f"в каталоге {source} мимо интерфейса. Примите их на странице "
                f"«Документы» или загрузите документы через интерфейс."
            )
        raise FileNotFoundError(f"В каталоге {source} не найдено поддерживаемых файлов")

    documents = []
    skipped: list[tuple[str, str]] = []
    facts: dict[str, dict[str, Any]] = {}
    for path in files:
        try:
            doc = loaders.load(path)
        except Exception as exc:
            skipped.append((str(path), str(exc)))
            say(f"  ! пропущен {path.name}: {exc}")
            continue
        if not doc.blocks:
            skipped.append((str(path), "не удалось извлечь текст (возможно, скан без OCR)"))
            say(f"  ! пустой текст: {path.name}")
            continue
        facts[doc.path] = _file_facts(path, doc.checksum)
        documents.append(doc)
        say(f"  + {path.name}: {len(doc.blocks)} блоков")

    chunks = chunk_documents(documents, cfg.chunking)
    if not chunks:
        raise ValueError("После чанкинга не осталось текста — проверьте исходные файлы")
    say(f"Чанков получено: {len(chunks)}")

    embedder = build_embedder(cfg.embedding)
    say(f"Эмбеддинги: {embedder.name}")
    vectors = embedder.embed_documents([c.embed_text for c in chunks])

    store = create_store(cfg)
    say(f"Хранилище: {store.backend_name}")
    store.build(
        chunks,
        vectors,
        embedder_name=embedder.name,
        embedder_state=embedder.state(),
        extra={
            "built_at": datetime.now(timezone.utc).isoformat(),
            "chunk_size": cfg.chunking.size,
            "chunk_overlap": cfg.chunking.overlap,
            "skipped": skipped,
        },
    )
    # Факты о файлах кладём после сборки: манифест описывает индекс, а
    # mtime/sha256 относятся к исходникам и берутся из файловой системы.
    store.set_document_facts(facts)
    store.save()

    return IndexReport(
        files=len(documents),
        chunks=len(chunks),
        skipped=skipped,
        elapsed=time.time() - started,
        embedder=embedder.name,
        store_backend=store.backend_name,
        excluded=[str(path) for path in excluded],
    )


def update_documents(
    cfg: Settings,
    paths: list[str | Path],
    *,
    progress: Callable[[str], None] | None = None,
    allow: Callable[[str], bool] | None = None,
) -> IndexReport:
    """Добавляет или обновляет отдельные документы без полной переиндексации.

    Работает только на бэкенде chroma: у него есть upsert и delete по id.
    numpy-хранилище держит одну матрицу целиком, и точечная правка в нём
    означала бы перезапись всего файла — проще пересобрать индекс.
    """
    from .store import ChromaStore

    started = time.time()
    say = progress or (lambda _msg: None)

    store = open_store(cfg)
    if not isinstance(store, ChromaStore):
        raise ValueError(
            "Инкрементальное обновление доступно только при store.backend: chroma. "
            "Для numpy выполните полную переиндексацию: ragkb index --rebuild"
        )

    embedder = build_embedder(cfg.embedding)
    if store.embedder_state:
        embedder.load_state(store.embedder_state)

    warnings: list[str] = []
    if isinstance(embedder, TfidfEmbedder):
        # Словарь IDF заморожен на момент полной индексации: слова, которых не
        # было в корпусе, получают нейтральный вес, и новые документы хуже
        # находятся плотным поиском. У нейросетевых эмбеддеров этого нет.
        warnings.append(
            "Эмбеддер TF-IDF: словарь IDF не обновляется при инкрементальной "
            "загрузке — новые термины получат нейтральный вес. Периодически "
            "выполняйте полную переиндексацию или используйте нейросетевой эмбеддер."
        )

    total_chunks = 0
    skipped: list[tuple[str, str]] = []
    facts: dict[str, dict[str, Any]] = {}
    for path in paths:
        for file_path in loaders.discover(path):
            if allow is not None and not allow(
                loaders.relative_name(file_path, Path(cfg.docs_dir))
            ):
                skipped.append((str(file_path), "вне корпуса: не принят через интерфейс"))
                continue
            try:
                doc = loaders.load(file_path)
            except Exception as exc:
                skipped.append((str(file_path), str(exc)))
                continue
            chunks = chunk_documents([doc], cfg.chunking)
            if not chunks:
                skipped.append((str(file_path), "пустой текст"))
                continue
            vectors = embedder.embed_documents([c.embed_text for c in chunks])
            store.upsert_document(chunks, vectors)
            facts[doc.path] = _file_facts(file_path, doc.checksum)
            total_chunks += len(chunks)
            say(f"  ~ {file_path.name}: {len(chunks)} чанков обновлено")

    store.set_document_facts(facts)
    store.save()
    return IndexReport(
        files=len(paths),
        chunks=total_chunks,
        skipped=skipped,
        elapsed=time.time() - started,
        embedder=embedder.name,
        store_backend=store.backend_name,
        warnings=warnings,
    )


def _accepted_only(
    files: list[Path], source: Path, allow: Callable[[str], bool] | None
) -> tuple[list[Path], list[Path]]:
    """Делит найденные файлы на принятые в корпус и оставшиеся в стороне."""
    if allow is None:
        return list(files), []
    accepted: list[Path] = []
    excluded: list[Path] = []
    for path in files:
        name = loaders.relative_name(path, source)
        (accepted if allow(name) else excluded).append(path)
    return accepted, excluded


def _file_facts(path: str | Path, checksum: str) -> dict[str, Any]:
    """Факты о файле для манифеста.

    Хэш содержимого и размер отвечают на вопрос «тот ли это документ», а
    mtime — «менялся ли он после индексации». Вместе они надёжнее, чем
    сравнение с временем сборки индекса: переиндексация соседнего файла
    больше не делает вид, что изменились все.
    """
    stat = Path(path).stat()
    return {
        "mtime": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
        "size": stat.st_size,
        "sha256": checksum,
    }


def parse_expanded_queries(raw: str, question: str, n: int) -> list[str]:
    """Достаёт перефразировки вопроса из ответа модели.

    Контракт — JSON `{"queries": [...]}`: он переживает и нумерацию, и
    вводные пояснения. Модели поменьше его нарушают, поэтому есть запасной
    разбор по строкам: одна кривая перефразировка полезнее, чем ни одной.
    Исходный вопрос и повторы отбрасываем — они уже есть в поиске.
    """
    queries = _queries_from_json(raw)
    if not queries:
        queries = [
            re.sub(r"^[\d\-.)\s]+", "", line).strip() for line in raw.splitlines()
        ]
    out: list[str] = []
    seen = {_normalized(question)}
    for query in queries:
        candidate = " ".join(query.split())
        key = _normalized(candidate)
        if len(candidate) <= 5 or key in seen:
            continue
        seen.add(key)
        out.append(candidate)
        if len(out) >= n:
            break
    return out


def _queries_from_json(raw: str) -> list[str]:
    """Вырезает список перефразировок из ответа, если он похож на JSON.

    Ищем по внешним фигурным скобкам, а не парсим строку целиком: модель
    часто обрамляет JSON пояснением или блоком ```json.
    """
    start, end = raw.find("{"), raw.rfind("}")
    if start < 0 or end <= start:
        return []
    try:
        body = json.loads(raw[start : end + 1])
    except ValueError:
        return []
    if not isinstance(body, dict):
        return []
    values = body.get("queries") or body.get("questions") or []
    if not isinstance(values, list):
        return []
    return [value for value in values if isinstance(value, str)]


def _normalized(text: str) -> str:
    return " ".join(text.split()).casefold()


def remove_document(cfg: Settings, path: str | Path) -> int:
    """Удаляет документ из индекса по исходному пути. Возвращает число чанков."""
    from .store import ChromaStore

    store = open_store(cfg)
    if not isinstance(store, ChromaStore):
        raise ValueError("Удаление доступно только при store.backend: chroma")
    target = str(Path(path))
    doc_ids = {
        c.doc_id
        for c in store.chunks
        if c.source == target or Path(c.source).name == Path(target).name
    }
    removed = sum(store.delete_document(doc_id) for doc_id in doc_ids)
    store.save()
    return removed


# ------------------------------------------------------------------------ RAG

class RAGPipeline:
    def __init__(self, cfg: Settings):
        self.cfg = cfg
        self.store: BaseStore = open_store(cfg)
        self.embedder = self._restore_embedder()
        self.retriever = Retriever(self.store, self.embedder, cfg.retrieval)
        self.llm: LLM = build_llm(cfg.llm)

    def _restore_embedder(self) -> Embedder:
        """Эмбеддер запроса обязан совпадать с тем, чем строился индекс."""
        indexed_with = self.store.manifest.get("embedder", "")
        embedder = build_embedder(self.cfg.embedding)
        if indexed_with and embedder.name != indexed_with:
            raise ValueError(
                f"Индекс построен эмбеддером «{indexed_with}», а конфиг требует "
                f"«{embedder.name}». Переиндексируйте базу или верните прежнюю модель."
            )
        state = self.store.embedder_state
        if state:
            embedder.load_state(state)
        return embedder

    def _llm_for(self, model: str | None) -> LLM:
        """Объект LLM под конкретный запрос.

        Построение дёшево — это обёртка над настройками, сама модель грузится
        в Ollama при первом обращении. Поэтому держать пул объектов незачем.

        Имя модели сюда приходит уже проверенным по списку разрешённых:
        проверка живёт в слое HTTP, ближе к источнику недоверенных данных.
        """
        if not model or model == self.cfg.llm.model:
            return self.llm
        return build_llm(replace(self.cfg.llm, model=model))

    # --------------------------------------------------------------- поиск

    def search(self, question: str, top_k: int | None = None, expand: bool = False) -> list[Hit]:
        if not expand:
            return self.retriever.search(question, top_k)
        queries = [question, *self._expand_query(question)]
        rankings: dict[str, list[tuple[str, float]]] = {}
        pool: dict[str, Hit] = {}
        for i, query in enumerate(queries):
            hits = self.retriever.search(query, top_k=self.cfg.retrieval.candidates)
            rankings[f"q{i}"] = [(h.chunk.chunk_id, h.score) for h in hits]
            for hit in hits:
                pool.setdefault(hit.chunk.chunk_id, hit)
        fused = reciprocal_rank_fusion(rankings, k=self.cfg.retrieval.rrf_k)
        result = []
        for chunk_id, score, _sources in fused[: (top_k or self.cfg.retrieval.top_k)]:
            hit = pool[chunk_id]
            hit.score = score
            result.append(hit)
        return result

    def _expand_query(self, question: str, n: int = 2) -> list[str]:
        try:
            raw = self.llm.generate(
                "Ты помогаешь искать по базе документов.",
                QUERY_EXPANSION_PROMPT.format(n=n, question=question),
            )
        except Exception:
            return []
        return parse_expanded_queries(raw, question, n)

    # ---------------------------------------------------------------- ответ

    def ask(
        self,
        question: str,
        *,
        top_k: int | None = None,
        history: list[tuple[str, str]] | None = None,
        expand: bool = False,
        model: str | None = None,
    ) -> Answer:
        started = time.time()
        warnings: list[str] = []
        llm = self._llm_for(model)

        search_query = question
        if history:
            search_query = self._condense(question, history, llm) or question

        hits = self.search(search_query, top_k=top_k, expand=expand)
        if not hits:
            return Answer(
                question=question,
                text="В базе знаний нет информации по этому вопросу.",
                hits=[],
                elapsed=time.time() - started,
                llm_backend=llm.name,
                warnings=["Поиск не вернул ни одного релевантного фрагмента"],
            )

        context = format_context(hits)
        prompt = ANSWER_TEMPLATE.format(context=context, question=question)
        try:
            text = llm.generate(SYSTEM_PROMPT, prompt)
        except LLMError as exc:
            warnings.append(f"{exc} — ответ собран экстрактивно")
            from .llm import ExtractiveLLM

            text = ExtractiveLLM(self.cfg.llm).generate(SYSTEM_PROMPT, prompt)

        used = self.cited_sources(text, hits)
        if not used and "нет информации" not in text.lower():
            warnings.append("Модель не проставила ссылки на источники — ответ стоит проверить")

        return Answer(
            question=question,
            text=text,
            hits=hits,
            used_sources=used,
            elapsed=time.time() - started,
            llm_backend=llm.name,
            warnings=warnings,
        )

    def stream_answer(
        self,
        question: str,
        *,
        top_k: int | None = None,
        history: list[tuple[str, str]] | None = None,
        expand: bool = False,
        model: str | None = None,
    ) -> tuple[list[Hit], Iterator[str]]:
        """Готовит поток ответа и отдаёт найденные фрагменты сразу.

        Кортеж, а не генератор, по одной причине: источники вычисляются
        по готовому тексту через cited_sources, но список Hit нужен
        вызывающему коду раньше — до того, как поток закончится. Генератор
        отдать его не может, не смешивая типы событий в одном потоке.

        Пустой список фрагментов означает, что поиск ничего не дал.
        """
        llm = self._llm_for(model)
        search_query = question
        if history:
            search_query = self._condense(question, history, llm) or question

        hits = self.search(search_query, top_k=top_k, expand=expand)
        if not hits:
            def nothing_found() -> Iterator[str]:
                yield "В базе знаний нет информации по этому вопросу."

            return [], nothing_found()

        prompt = ANSWER_TEMPLATE.format(context=format_context(hits), question=question)
        return hits, llm.stream(SYSTEM_PROMPT, prompt)

    # ------------------------------------------------------------ служебное

    def _condense(self, question: str, history: list[tuple[str, str]],
                  llm: LLM | None = None) -> str | None:
        window = self.cfg.history.window
        recent = history[-window:] if window > 0 else []
        formatted = "\n".join(f"Пользователь: {q}\nАссистент: {a}" for q, a in recent)
        try:
            return (llm or self.llm).generate(
                "Ты переформулируешь вопросы.",
                CONDENSE_PROMPT.format(history=formatted, question=question),
            ).strip()
        except Exception:
            return None

    def cited_sources(self, text: str, hits: list[Hit]) -> list[dict[str, Any]]:
        """Собирает список реально процитированных источников по маркерам [N].

        `text` — снапшот чанка на момент ответа (то, что видел LLM):
        если документ позже удалили, фрагмент остаётся виден.
        """
        return self._cited_sources(text, hits)

    def fallback_text(self, question: str, hits: list[Hit]) -> str:
        prompt = ANSWER_TEMPLATE.format(context=format_context(hits), question=question)
        from .llm import ExtractiveLLM

        return ExtractiveLLM(self.cfg.llm).generate(SYSTEM_PROMPT, prompt)

    def document_paths(self) -> set[str] | None:
        documents = self.store.manifest.get("documents", [])
        return {d.get("source", "") for d in documents}

    @staticmethod
    def _cited_sources(text: str, hits: list[Hit]) -> list[dict[str, Any]]:
        """Собирает список реально процитированных источников по маркерам [N].

        `text` — снапшот чанка на момент ответа (то, что видел LLM):
        если документ позже удалили, фрагмент остаётся виден.
        """
        numbers = {int(n) for n in re.findall(r"\[(\d+)\]", text)}
        out = []
        for i, hit in enumerate(hits, start=1):
            if i in numbers:
                out.append(
                    {
                        "n": i,
                        "citation": hit.chunk.citation(),
                        "source": hit.chunk.source,
                        "page": hit.chunk.page,
                        "score": round(hit.score, 4),
                        "text": hit.chunk.text,
                    }
                )
        return out

    def stats(self) -> dict[str, Any]:
        return {
            "chunks": len(self.store),
            "documents": len(self.store.manifest.get("documents", [])),
            "store": self.store.backend_name,
            "embedder": self.store.manifest.get("embedder"),
            "llm": self.llm.name,
            "llm_available": self.llm.available(),
            "index_dir": str(self.store.dir),
        }
