"""Кандидаты на скачивание: сопоставление названий и привязка к реестру.

Кандидаты — это подсказка модели, а не разрешение: документ попадает в набор
по названию из вопроса или по источнику найденного фрагмента, а разрешение
всегда берётся из реестра. Путей в наборе нет — только идентификаторы и имена.
"""
from __future__ import annotations

import uuid
from pathlib import Path

from helpers import MemoryRegistry
from langchain_core.documents import Document

from ragkb.core.answer_events import TOOL_NOT_AVAILABLE, attachment_result
from ragkb.core.config import Settings
from ragkb.core.retrieval import Hit
from ragkb.services.download_candidates import (
    download_resolver,
    match_names,
    prepare_candidates,
)
from ragkb.services.downloads import DownloadsService

PDF = b"%PDF-1.4 test\n"


def _hit(path: Path, text: str = "фрагмент документа") -> Hit:
    return Hit(document=Document(page_content=text, metadata={"source": str(path)}), score=1.0)


def _cfg(tmp_path: Path) -> Settings:
    docs = tmp_path / "docs"
    docs.mkdir(exist_ok=True)
    return Settings(docs_dir=str(docs), index_dir=str(tmp_path / "index"))


def _registry(tmp_path: Path, *names: str, allowed: bool = False) -> MemoryRegistry:
    cfg = _cfg(tmp_path)
    for name in names:
        (Path(cfg.docs_dir) / name).write_bytes(PDF)
    return MemoryRegistry().add(cfg, *names, download_allowed=allowed)


# --------------------------------------------------- сопоставление названий


def test_html5_does_not_silently_select_mobile():
    names = ["AdSmart HTML5.pdf", "AdSmart Mobile HTML5.pdf"]

    assert match_names("Пришли AdSmart Mobile HTML5", names) == [names[1]]
    assert set(match_names("Пришли требования HTML5", names)) == set(names)


def test_longest_name_wins_its_own_match():
    names = ["AdSmart MediaText.pdf", "AdSmart MediaText Premium.pdf"]

    assert match_names("Пришли AdSmart MediaText Premium", names) == [names[1]]
    assert set(match_names("Пришли требования MediaText", names)) == set(names)


def test_named_document_is_returned_without_neighbours():
    names = ["AdSmart Multi.pdf", "AdSmart Mobile HTML5.pdf", "AdSmart HTML5.pdf"]

    assert match_names("Пришли требования к AdSmart Multi", names) == ["AdSmart Multi.pdf"]


def test_case_and_punctuation_do_not_hide_the_name():
    names = ["AdSmart Mobile Slider.pdf"]

    assert match_names("пришли ADSMART mobile-slider?", names) == names


def test_service_words_alone_do_not_match_documents():
    names = ["Требования к размещению.pdf", "AdSmart Multi.pdf"]

    assert match_names("Пришли требования", names) == []
    assert match_names("", names) == []


# --------------------------------------------------------- набор кандидатов


async def test_only_registered_documents_from_docs_dir_become_candidates(tmp_path):
    """Привязка идёт по пути внутри каталога, а не по совпадению имени файла."""
    cfg = _cfg(tmp_path)
    docs = Path(cfg.docs_dir)
    (docs / "spec.pdf").write_bytes(PDF)
    (docs / "other.pdf").write_bytes(PDF)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (elsewhere / "spec.pdf").write_bytes(PDF)
    registry = MemoryRegistry().add(cfg, "spec.pdf")

    candidates = await prepare_candidates(
        "Что написано в документе",
        [_hit(docs / "spec.pdf"), _hit(docs / "other.pdf"), _hit(elsewhere / "spec.pdf")],
        registry,
        docs,
    )

    assert [candidate["filename"] for candidate in candidates] == ["spec.pdf"]
    assert "path" not in candidates[0]


async def test_closed_document_is_a_candidate_without_permission(tmp_path):
    registry = _registry(tmp_path, "faq.docx")
    docs = Path(registry.rows["faq.docx"].name)
    document_id = registry.rows["faq.docx"].document_id

    candidates = await prepare_candidates(
        "О чём база знаний", [_hit(docs)], registry, docs.parent
    )

    assert candidates == [
        {"document_id": document_id, "filename": "faq.docx", "download_allowed": False}
    ]


async def test_named_document_outside_top_k_is_a_candidate(tmp_path):
    """Ответ может опираться на закрытый DOCX, а приложить нужно разрешённый PDF."""
    cfg = _cfg(tmp_path)
    docs = Path(cfg.docs_dir)
    (docs / "faq.docx").write_bytes(PDF)
    (docs / "AdSmart Multi.pdf").write_bytes(PDF)
    registry = MemoryRegistry().add(cfg, "faq.docx", "AdSmart Multi.pdf", download_allowed=True)
    await registry.set_download_allowed(registry.rows["faq.docx"].document_id, False)

    candidates = await prepare_candidates(
        "Пришли требования к AdSmart Multi", [_hit(docs / "faq.docx")], registry, docs
    )

    assert {candidate["filename"]: candidate["download_allowed"] for candidate in candidates} == {
        "AdSmart Multi.pdf": True,
        "faq.docx": False,
    }


async def test_candidates_are_deduplicated_by_document_id(tmp_path):
    cfg = _cfg(tmp_path)
    docs = Path(cfg.docs_dir)
    (docs / "AdSmart Multi.pdf").write_bytes(PDF)
    registry = MemoryRegistry().add(cfg, "AdSmart Multi.pdf", download_allowed=True)

    candidates = await prepare_candidates(
        "Пришли AdSmart Multi", [_hit(docs / "AdSmart Multi.pdf")], registry, docs
    )

    assert len(candidates) == 1


async def test_many_hits_of_one_document_give_one_candidate(tmp_path):
    """Несколько фрагментов с одинаковым названием — всё ещё один документ."""
    cfg = _cfg(tmp_path)
    docs = Path(cfg.docs_dir)
    (docs / "policy.md").write_bytes(PDF)
    registry = MemoryRegistry().add(cfg, "policy.md", download_allowed=True)
    document_id = registry.rows["policy.md"].document_id

    candidates = await prepare_candidates(
        "Что сказано про отпуск",
        [_hit(docs / "policy.md", "первый"), _hit(docs / "policy.md", "второй")],
        registry,
        docs,
    )

    assert candidates == [
        {"document_id": document_id, "filename": "policy.md", "download_allowed": True}
    ]


async def test_too_many_matches_give_no_candidates(tmp_path):
    """Слишком широкая подборка хуже пустой: модель должна уточнить запрос."""
    cfg = _cfg(tmp_path)
    docs = Path(cfg.docs_dir)
    names = [f"AdSmart HTML5 вариант {index}.pdf" for index in range(25)]
    for name in names:
        (docs / name).write_bytes(PDF)
    registry = MemoryRegistry().add(cfg, *names, download_allowed=True)

    assert len(match_names("Пришли требования HTML5", names)) == 25
    assert await prepare_candidates("Пришли требования HTML5", [], registry, docs) == []


async def test_without_registry_there_are_no_candidates(tmp_path):
    cfg = _cfg(tmp_path)
    docs = Path(cfg.docs_dir)
    (docs / "spec.pdf").write_bytes(PDF)

    assert await prepare_candidates("Пришли spec.pdf", [_hit(docs / "spec.pdf")], None, docs) == []
    resolve = download_resolver(DownloadsService(docs, None), [])
    assert await resolve(str(uuid.uuid4())) == {"error": TOOL_NOT_AVAILABLE}


# --------------------------------------------------------- обработчик инструмента


async def test_resolver_returns_attachment_metadata(tmp_path):
    cfg = _cfg(tmp_path)
    docs = Path(cfg.docs_dir)
    (docs / "spec.pdf").write_bytes(PDF)
    registry = MemoryRegistry().add(cfg, "spec.pdf", download_allowed=True)
    document_id = registry.rows["spec.pdf"].document_id
    candidates = await prepare_candidates("Пришли spec.pdf", [], registry, docs)

    resolve = download_resolver(DownloadsService(docs, registry), candidates)
    result = await resolve(document_id)

    assert result == {
        "document_id": document_id,
        "filename": "spec.pdf",
        "url": f"/api/documents/{document_id}/download",
        "media_type": "application/pdf",
        "size": len(PDF),
    }
    assert "path" not in result


async def test_resolver_refuses_ids_outside_the_candidate_set(tmp_path):
    cfg = _cfg(tmp_path)
    docs = Path(cfg.docs_dir)
    (docs / "spec.pdf").write_bytes(PDF)
    (docs / "closed.pdf").write_bytes(PDF)
    registry = MemoryRegistry().add(cfg, "spec.pdf", "closed.pdf", download_allowed=True)
    closed_id = registry.rows["closed.pdf"].document_id
    await registry.set_download_allowed(closed_id, False)
    candidates = await prepare_candidates("Пришли spec.pdf", [], registry, docs)
    resolve = download_resolver(DownloadsService(docs, registry), candidates)

    # Чужой идентификатор и закрытый документ одинаково недоступны.
    assert await resolve(str(uuid.uuid4())) == {"error": TOOL_NOT_AVAILABLE}
    assert await resolve(closed_id) == {"error": TOOL_NOT_AVAILABLE}


async def test_resolver_sees_revoked_permission(tmp_path):
    """Разрешение перечитывается при вызове: отзыв после подготовки действует."""
    cfg = _cfg(tmp_path)
    docs = Path(cfg.docs_dir)
    (docs / "spec.pdf").write_bytes(PDF)
    registry = MemoryRegistry().add(cfg, "spec.pdf", download_allowed=True)
    document_id = registry.rows["spec.pdf"].document_id
    candidates = await prepare_candidates("Пришли spec.pdf", [], registry, docs)
    resolve = download_resolver(DownloadsService(docs, registry), candidates)

    await registry.set_download_allowed(document_id, False)

    assert await resolve(document_id) == {"error": TOOL_NOT_AVAILABLE}


async def test_resolver_refuses_when_the_file_disappeared(tmp_path):
    cfg = _cfg(tmp_path)
    docs = Path(cfg.docs_dir)
    (docs / "spec.pdf").write_bytes(PDF)
    registry = MemoryRegistry().add(cfg, "spec.pdf", download_allowed=True)
    document_id = registry.rows["spec.pdf"].document_id
    candidates = await prepare_candidates("Пришли spec.pdf", [], registry, docs)
    resolve = download_resolver(DownloadsService(docs, registry), candidates)
    (docs / "spec.pdf").unlink()

    assert await resolve(document_id) == {"error": TOOL_NOT_AVAILABLE}

# --------------------------------------------------------------- граница API


def test_attachment_dto_accepts_the_tool_result():
    """Форма результата инструмента совпадает с вложением в ответе.

    Ядро отдаёт обычный словарь, а граница API описывает его моделью: если они
    разойдутся, карточка файла в интерфейсе сломается молча.
    """
    from ragkb.api.schemas.downloads import Attachment

    document_id = str(uuid.uuid4())
    result = attachment_result(
        document_id=document_id, filename="spec.pdf", media_type="application/pdf", size=len(PDF)
    )

    attachment = Attachment(**result)

    assert attachment.document_id == uuid.UUID(document_id)
    assert attachment.url == f"/api/documents/{document_id}/download"
    assert attachment.size == len(PDF)


def test_done_event_keeps_existing_fields_and_adds_attachments():
    from ragkb.api.schemas.ask import DoneEvent, TokenEvent

    done = DoneEvent(
        sources=[{"n": 1}], warnings=["предупреждение"], elapsed_sec=1.5, model="m", truncated=True
    ).model_dump(mode="json")
    token = TokenEvent(text="часть").model_dump(mode="json")

    assert done["attachments"] == []
    assert done["truncated"] is True
    assert done["sources"] == [{"n": 1}]
    assert token == {"type": "token", "text": "часть"}
