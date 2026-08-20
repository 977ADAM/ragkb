"""HTTP API на FastAPI + минимальный веб-интерфейс."""
from __future__ import annotations

import json
import time
from collections.abc import Iterator
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse, StreamingResponse
from pydantic import BaseModel, Field

from .auth import User, current_user, optional_user, require_admin
from .config import Config
from .history import HistoryStore, make_title
from .llm import ExtractiveLLM
from .models import available_models, resolve_model
from .pipeline import ANSWER_TEMPLATE, SYSTEM_PROMPT, RAGPipeline, build_index, format_context
from .ui import UI_HTML


class AskRequest(BaseModel):
    question: str = Field(..., min_length=2)
    # Границы: ноль фрагментов бессмысленен, а больше двадцати не поместится
    # в разумный промпт. Число фрагментов — самый сильный рычаг скорости
    # на машине без ускорителя.
    top_k: int | None = Field(None, ge=1, le=20)
    expand: bool = False
    # Историю в теле запроса присылают программные клиенты. Веб-интерфейс
    # передаёт conversation_id, а историю подгружает сервер — иначе работа
    # с разных устройств невозможна.
    history: list[tuple[str, str]] = Field(default_factory=list)
    conversation_id: str | None = None
    # Пустое значение означает «модель по умолчанию из настроек».
    model: str | None = None


class ModelInfo(BaseModel):
    """Модель, доступная для выбора."""

    id: str
    display_name: str | None = None
    context_window: int | None = None
    supports_tools: bool = False
    is_default: bool = False


class ModelsResponse(BaseModel):
    models: list[ModelInfo]


class SearchRequest(BaseModel):
    query: str = Field(..., min_length=2)
    top_k: int = 5


def create_app(cfg: Config) -> FastAPI:
    # /docs, /redoc, /openapi.json отключены: FastAPI отдаёт их без проверки
    # аутентификации (зависимости current_user там не участвуют). Снаружи
    # закрыты прокси, но любой сосед по сети compose иначе прочитал бы полную
    # схему API без единого заголовка.
    app = FastAPI(
        title="RAG База знаний",
        version="1.0",
        # Схема API закрыта: снаружи её прячет прокси, но внутри сети compose
        # её прочитал бы любой сосед.
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )

    # Зависимости идентификации читают настройки отсюда.
    app.state.auth = cfg.auth
    if cfg.auth.mode == "disabled":
        print(
            "ВНИМАНИЕ: аутентификация выключена (auth.mode: disabled). \
            Все запросы выполняются от имени «anonymous». \
            В общем контуре так работать нельзя."
        )
    if cfg.llm.available and cfg.llm.model not in {
        e.get("name", "") for e in cfg.llm.available
    }:
        # Не отказ: опечатка администратора в llm.model не должна превращать
        # каждый запрос без явной model в 400-ю ошибку (resolve_model честно
        # вернёт cfg.model). Но /models тогда не пометит default, браузер
        # возьмёт первый пункт списка, а пустой запрос уйдёт на cfg.model —
        # предупреждаем об этом расхождении при старте.
        print(
            f"ВНИМАНИЕ: llm.model «{cfg.llm.model}» отсутствует в llm.available. \
            Список моделей в интерфейсе разойдётся с моделью по умолчанию."
        )

    state: dict[str, Any] = {"pipeline": None, "error": None}

    def pipeline() -> RAGPipeline:
        if state["pipeline"] is None:
            try:
                state["pipeline"] = RAGPipeline(cfg)
                state["error"] = None
            except Exception as exc:
                state["error"] = str(exc)
                raise HTTPException(status_code=503, detail=str(exc)) from exc
        return state["pipeline"]

    # Хранилище строится сразу, а не лениво: спека требует, чтобы несовместимая
    # версия схемы валила сервис при старте с внятным сообщением. При ленивом
    # создании она вылезла бы 500-й ошибкой на первом запросе пользователя.
    history_store: HistoryStore | None = (
        HistoryStore(cfg.history.path, retention_days=cfg.history.retention_days)
        if cfg.history.enabled
        else None
    )

    def known_sources() -> set[str] | None:
        """Пути документов, которые сейчас есть в индексе.

        None — состав узнать не удалось (индекс не построен или недоступен).
        Тогда пометку не ставим вовсе: «источник неизвестен» честнее,
        чем «источника нет».
        """
        try:
            documents = pipeline().store.manifest.get("documents", [])
        except HTTPException:
            return None
        return {d.get("source", "") for d in documents}

    def mark_availability(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Помечает источники, которых больше нет в базе знаний.

        Диалог хранит ссылку на документ, а не его текст. Документ могли
        удалить из корпуса — тогда интерфейс должен сказать об этом, а не
        показать пустоту или ошибку.
        """
        sources = known_sources()
        if sources is None:
            return messages
        for message in messages:
            for source in message.get("sources", []):
                source["available"] = source.get("source") in sources
        return messages

    @app.get("/health")
    def health(user: User | None = Depends(optional_user)) -> dict[str, Any]:
        # Без аутентификации отдаём только статус: HEALTHCHECK должен работать,
        # но состав индекса, имя эмбеддера и пути наружу не уходят.
        try:
            stats = pipeline().stats()
        except HTTPException as exc:
            return {"status": "no_index"} if user is None else {
                "status": "no_index",
                "detail": exc.detail,
            }
        return {"status": "ok"} if user is None else {"status": "ok", **stats}


    @app.get(
        "/models",
        response_model=ModelsResponse,
        dependencies=[Depends(current_user)],
    )
    def list_models() -> ModelsResponse:
        # probe=True добирает размер контекста и поддержку инструментов из Ollama.
        # Отказ Ollama список не роняет: недостающие поля останутся пустыми.
        return ModelsResponse(
            models=[ModelInfo(**item) for item in available_models(cfg.llm, probe=True)]
        )




    @app.post("/ask")
    def ask(req: AskRequest, user: User = Depends(current_user)) -> dict[str, Any]:
        try:
            model = resolve_model(cfg.llm, req.model)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        store = history_store
        conversation_id = req.conversation_id
        turns: list[tuple[str, str]] | None = [(q, a) for q, a in req.history] or None

        if store is not None:
            store.cleanup()
            if conversation_id:
                if not store.owns(conversation_id, user.name):
                    # Чужой или несуществующий — один и тот же ответ:
                    # по коду ответа нельзя узнать, что диалог существует.
                    raise HTTPException(status_code=404, detail="Диалог не найден")
                turns = store.recent_turns(
                    conversation_id, user.name, cfg.history.window
                ) or turns

        answer = pipeline().ask(
            req.question, top_k=req.top_k, history=turns, expand=req.expand, model=model
        )

        data = answer.to_dict()
        data["model"] = model

        if store is not None:
            # Диалог заводим только после успешного ответа пайплайна: иначе
            # при ошибке генерации (нет индекса, недоступна LLM и т.п.) в базе
            # оставался бы диалог без единого сообщения — клиент к тому же
            # не получил бы conversation_id, ведь исключение обрывает выдачу
            # JSON, и продолжить или удалить такой диалог было бы нечем.
            if not conversation_id:
                conversation_id = store.create_conversation(
                    user.name, make_title(req.question)
                )
            # Ответ уже получен и стоил дорого (обращение к модели) —
            # отдать его пользователю важнее, чем сохранить в историю.
            # Поэтому запись не должна ронять запрос: ни отказ (False —
            # диалог исчез между owns() и записью, например его убрала
            # cleanup() соседнего запроса), ни исключение (истёк таймаут
            # блокировки SQLite) не должны стоить пользователю 500-й ошибки
            # после того, как ответ уже посчитан.
            try:
                saved_question = store.append(
                    conversation_id, user.name, "user", req.question
                )
                saved_answer = store.append(
                    conversation_id, user.name, "assistant",
                    answer.text, answer.used_sources, model=model,
                )
                if not (saved_question and saved_answer):
                    data["warnings"].append(
                        "Ответ не сохранён в историю диалога"
                    )
            except Exception:
                data["warnings"].append(
                    "Ответ не сохранён в историю диалога"
                )

        data["conversation_id"] = conversation_id
        return data

    @app.post("/ask/stream")
    def ask_stream(req: AskRequest, user: User = Depends(current_user)) -> StreamingResponse:
        try:
            model = resolve_model(cfg.llm, req.model)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        store = history_store
        conversation_id = req.conversation_id
        turns: list[tuple[str, str]] | None = [(q, a) for q, a in req.history] or None

        if store is not None:
            store.cleanup()
            if conversation_id:
                if not store.owns(conversation_id, user.name):
                    # Чужой и несуществующий неотличимы по ответу.
                    raise HTTPException(status_code=404, detail="Диалог не найден")
                turns = store.recent_turns(
                    conversation_id, user.name, cfg.history.window
                ) or turns

        # Поиск и подготовка потока выполняются здесь, до отдачи первого байта:
        # пока статус ответа не отправлен, об отказе ещё можно сообщить кодом.
        started = time.time()
        rag = pipeline()
        hits, tokens = rag.stream_answer(
            req.question, top_k=req.top_k, history=turns, model=model
        )

        def generate() -> Iterator[str]:
            nonlocal conversation_id
            collected: list[str] = []
            warnings: list[str] = []
            try:
                try:
                    for piece in tokens:
                        collected.append(piece)
                        yield json.dumps(
                            {"type": "token", "text": piece}, ensure_ascii=False
                        ) + "\n"
                except Exception as exc:
                    if collected:
                        # Часть ответа уже ушла клиенту — подставлять
                        # экстрактивный текст поверх нельзя, он задвоится.
                        # Статус уже отправлен и равен 200 — сменить его
                        # нельзя, поэтому об отказе сообщаем событием.
                        yield json.dumps(
                            {"type": "error", "detail": str(exc)}, ensure_ascii=False
                        ) + "\n"
                        return
                    # Ни одного токена ещё не отдано — деградируем так же,
                    # как /ask при LLMError: экстрактивный ответ по найденным
                    # фрагментам вместо жёсткой ошибки.
                    warnings.append(f"{exc} — ответ собран экстрактивно")
                    prompt = ANSWER_TEMPLATE.format(
                        context=format_context(hits), question=req.question
                    )
                    fallback_text = ExtractiveLLM(cfg.llm).generate(
                        SYSTEM_PROMPT, prompt
                    )
                    collected.append(fallback_text)
                    yield json.dumps(
                        {"type": "token", "text": fallback_text}, ensure_ascii=False
                    ) + "\n"

                text = "".join(collected)
                # Считаем один раз: то же самое уходит и в историю, и в событие done.
                sources = RAGPipeline._cited_sources(text, hits)

                if not hits:
                    warnings.append("Поиск не вернул ни одного релевантного фрагмента")
                if not sources and "нет информации" not in text.lower():
                    warnings.append(
                        "Модель не проставила ссылки на источники — ответ стоит проверить"
                    )

                if store is not None:
                    # Диалог заводим только после успешной генерации — как в /ask.
                    if not conversation_id:
                        conversation_id = store.create_conversation(
                            user.name, make_title(req.question)
                        )
                    # Ответ уже отдан пользователю, отказ записи не должен его портить.
                    try:
                        saved_question = store.append(
                            conversation_id, user.name, "user", req.question
                        )
                        saved_answer = store.append(
                            conversation_id, user.name, "assistant", text, sources,
                            model=model,
                        )
                        if not (saved_question and saved_answer):
                            warnings.append("Ответ не сохранён в историю диалога")
                    except Exception:
                        warnings.append("Ответ не сохранён в историю диалога")

                yield json.dumps(
                    {
                        "type": "done",
                        "conversation_id": conversation_id,
                        "sources": sources,
                        "warnings": warnings,
                        "elapsed_sec": round(time.time() - started, 2),
                        "model": model,
                    },
                    ensure_ascii=False,
                ) + "\n"
            except Exception as exc:
                # Отказ где-то после цикла токенов (например, «database is
                # locked» при записи истории) не должен обрывать поток без
                # терминального события — клиент должен узнать об этом.
                yield json.dumps(
                    {"type": "error", "detail": str(exc)}, ensure_ascii=False
                ) + "\n"

        return StreamingResponse(
            generate(), media_type="application/x-ndjson; charset=utf-8"
        )

    @app.post("/search")
    def search(req: SearchRequest, user: User = Depends(current_user)) -> dict[str, Any]:
        hits = pipeline().search(req.query, top_k=req.top_k)
        return {"query": req.query, "results": [h.to_dict() for h in hits]}

    def require_history() -> HistoryStore:
        store = history_store
        if store is None:
            raise HTTPException(status_code=404, detail="История диалогов выключена")
        return store

    @app.get("/conversations")
    def list_conversations(
        user: User = Depends(current_user),
        limit: int = Query(50, ge=1, le=500),
        offset: int = Query(0, ge=0),
    ) -> dict[str, Any]:
        store = require_history()
        return {
            "conversations": [
                c.to_dict()
                for c in store.list_conversations(user.name, limit=limit, offset=offset)
            ],
            "total": store.count_conversations(user.name),
        }

    @app.get("/conversations/{conversation_id}")
    def get_conversation(
        conversation_id: str, user: User = Depends(current_user)
    ) -> dict[str, Any]:
        store = require_history()
        messages = store.get_messages(conversation_id, user.name)
        if messages is None:
            # Чужой и несуществующий неотличимы по ответу.
            raise HTTPException(status_code=404, detail="Диалог не найден")
        return {
            "id": conversation_id,
            "messages": mark_availability([m.to_dict() for m in messages]),
        }

    @app.delete("/conversations/{conversation_id}")
    def delete_conversation(
        conversation_id: str, user: User = Depends(current_user)
    ) -> dict[str, Any]:
        store = require_history()
        if not store.delete_conversation(conversation_id, user.name):
            raise HTTPException(status_code=404, detail="Диалог не найден")
        return {"deleted": True}

    @app.post("/reindex")
    def reindex(user: User = Depends(require_admin)) -> dict[str, Any]:
        report = build_index(cfg)
        state["pipeline"] = None  # индекс изменился — перезагружаем при следующем запросе
        return {
            "files": report.files,
            "chunks": report.chunks,
            "skipped": report.skipped,
            "elapsed_sec": round(report.elapsed, 1),
        }

    @app.get("/", response_class=HTMLResponse)
    def index_page(user: User = Depends(current_user)) -> str:
        return UI_HTML

    return app
