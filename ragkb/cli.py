"""Командная строка: ragkb index | ask | search | serve | eval | stats."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .config import Config
from .evaluation import evaluate, load_cases
from .pipeline import RAGPipeline, build_index, remove_document, update_documents
from .store import create_store

DEFAULT_CONFIG = "config.yaml"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="ragkb",
        description="Локальная RAG-система над базой знаний (PDF/DOCX/MD/TXT/HTML)",
    )
    parser.add_argument("-c", "--config", default=DEFAULT_CONFIG, help="путь к config.yaml")
    sub = parser.add_subparsers(dest="command", required=True)

    p_index = sub.add_parser("index", help="проиндексировать документы")
    p_index.add_argument("path", nargs="?", help="каталог или файл (по умолчанию из конфига)")
    p_index.add_argument("--rebuild", action="store_true", help="удалить старый индекс")

    p_update = sub.add_parser(
        "update", help="добавить/обновить отдельные документы (только chroma)"
    )
    p_update.add_argument("paths", nargs="+", help="файлы или каталоги")

    p_delete = sub.add_parser("delete", help="удалить документ из индекса (только chroma)")
    p_delete.add_argument("path", help="путь к исходному файлу")

    p_ask = sub.add_parser("ask", help="задать вопрос")
    p_ask.add_argument("question", nargs="+")
    p_ask.add_argument("-k", "--top-k", type=int, default=None)
    p_ask.add_argument("--expand", action="store_true", help="расширить запрос перефразировками")
    p_ask.add_argument("--json", action="store_true", help="вывести JSON")
    p_ask.add_argument("--show-chunks", action="store_true", help="показать найденные фрагменты")

    p_search = sub.add_parser("search", help="только поиск, без генерации")
    p_search.add_argument("query", nargs="+")
    p_search.add_argument("-k", "--top-k", type=int, default=5)

    p_serve = sub.add_parser("serve", help="запустить HTTP API и веб-интерфейс")
    p_serve.add_argument("--host", default="127.0.0.1")
    p_serve.add_argument("--port", type=int, default=8000)

    p_eval = sub.add_parser("eval", help="оценить качество поиска на тестовом наборе")
    p_eval.add_argument("dataset", help="JSONL с вопросами")
    p_eval.add_argument("-k", "--top-k", type=int, default=5)

    sub.add_parser("stats", help="информация об индексе")
    sub.add_parser("chat", help="интерактивный диалог")

    args = parser.parse_args(argv)
    cfg = Config.load(args.config)

    if args.command == "index":
        return _cmd_index(cfg, args)
    if args.command == "update":
        return _cmd_update(cfg, args)
    if args.command == "delete":
        return _cmd_delete(cfg, args)
    if args.command == "ask":
        return _cmd_ask(cfg, args)
    if args.command == "search":
        return _cmd_search(cfg, args)
    if args.command == "serve":
        return _cmd_serve(cfg, args)
    if args.command == "eval":
        return _cmd_eval(cfg, args)
    if args.command == "stats":
        return _cmd_stats(cfg)
    if args.command == "chat":
        return _cmd_chat(cfg)
    return 1


def _cmd_index(cfg: Config, args) -> int:
    if args.rebuild:
        create_store(cfg).clear()
        print("Старый индекс удалён")
    print(f"Индексация: {args.path or cfg.docs_dir}")
    try:
        report = build_index(cfg, docs_dir=args.path, progress=print)
    except (FileNotFoundError, ValueError, RuntimeError) as exc:
        print(f"Ошибка: {exc}", file=sys.stderr)
        return 1
    print(
        f"\nГотово за {report.elapsed:.1f} с: {report.files} документов, "
        f"{report.chunks} чанков, эмбеддер {report.embedder}, "
        f"хранилище {report.store_backend}"
    )
    if report.skipped:
        print(f"Пропущено файлов: {len(report.skipped)}")
        for path, reason in report.skipped:
            print(f"  - {Path(path).name}: {reason}")
    return 0


def _cmd_update(cfg: Config, args) -> int:
    try:
        report = update_documents(cfg, args.paths, progress=print)
    except (FileNotFoundError, ValueError, RuntimeError) as exc:
        print(f"Ошибка: {exc}", file=sys.stderr)
        return 1
    print(f"\nОбновлено за {report.elapsed:.1f} с: {report.chunks} чанков")
    for path, reason in report.skipped:
        print(f"  - {Path(path).name}: {reason}")
    for warning in report.warnings:
        print(f"\n⚠ {warning}")
    return 0


def _cmd_delete(cfg: Config, args) -> int:
    try:
        removed = remove_document(cfg, args.path)
    except (FileNotFoundError, ValueError, RuntimeError) as exc:
        print(f"Ошибка: {exc}", file=sys.stderr)
        return 1
    print(f"Удалено чанков: {removed}" if removed else "Документ в индексе не найден")
    return 0


def _cmd_ask(cfg: Config, args) -> int:
    pipeline = _load_pipeline(cfg)
    if pipeline is None:
        return 1
    question = " ".join(args.question)
    answer = pipeline.ask(question, top_k=args.top_k, expand=args.expand)

    if args.json:
        print(json.dumps(answer.to_dict(), ensure_ascii=False, indent=2))
        return 0

    print(f"\n{answer.text}\n")
    if answer.used_sources:
        print("Источники:")
        for src in answer.used_sources:
            print(f"  [{src['n']}] {src['citation']}  ({src['source']})")
    if args.show_chunks:
        print("\nНайденные фрагменты:")
        for i, hit in enumerate(answer.hits, start=1):
            preview = hit.chunk.text[:200].replace("\n", " ")
            print(f"  [{i}] score={hit.score:.4f} {hit.chunk.citation()}\n      {preview}…")
    for warning in answer.warnings:
        print(f"\n⚠ {warning}")
    print(f"\n({answer.elapsed:.1f} с, {answer.llm_backend})")
    return 0


def _cmd_search(cfg: Config, args) -> int:
    pipeline = _load_pipeline(cfg)
    if pipeline is None:
        return 1
    hits = pipeline.search(" ".join(args.query), top_k=args.top_k)
    if not hits:
        print("Ничего не найдено")
        return 0
    for i, hit in enumerate(hits, start=1):
        marks = "+".join(hit.rank_sources)
        print(f"\n[{i}] {hit.score:.4f} ({marks}) — {hit.chunk.citation()}")
        print(f"    {hit.chunk.text[:300]}".replace("\n", "\n    "))
    return 0


def _cmd_serve(cfg: Config, args) -> int:
    import uvicorn

    from .api import create_app

    app = create_app(cfg)
    print(f"Веб-интерфейс: http://{args.host}:{args.port}/")
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")
    return 0


def _cmd_eval(cfg: Config, args) -> int:
    pipeline = _load_pipeline(cfg)
    if pipeline is None:
        return 1
    cases = load_cases(args.dataset)
    result = evaluate(pipeline, cases, top_k=args.top_k)
    print(result.summary())
    if result.failures:
        print("\nНе найдено:")
        for failure in result.failures:
            print(f"  ? {failure['question']}")
            print(f"    ожидалось: {failure['expected']}")
            print(f"    получено:  {failure['got'][:3]}")
    return 0


def _cmd_stats(cfg: Config) -> int:
    pipeline = _load_pipeline(cfg)
    if pipeline is None:
        return 1
    for key, value in pipeline.stats().items():
        print(f"{key:16} {value}")
    return 0


def _cmd_chat(cfg: Config) -> int:
    pipeline = _load_pipeline(cfg)
    if pipeline is None:
        return 1
    print("Диалог с базой знаний. Пустая строка или Ctrl-C — выход.\n")
    history: list[tuple[str, str]] = []
    while True:
        try:
            question = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if not question:
            return 0
        answer = pipeline.ask(question, history=history)
        print(f"\n{answer.text}\n")
        for src in answer.used_sources:
            print(f"  [{src['n']}] {src['citation']}")
        print()
        history.append((question, answer.text))


def _load_pipeline(cfg: Config) -> RAGPipeline | None:
    try:
        return RAGPipeline(cfg)
    except (FileNotFoundError, ValueError) as exc:
        print(f"Ошибка: {exc}", file=sys.stderr)
        return None


if __name__ == "__main__":
    raise SystemExit(main())
