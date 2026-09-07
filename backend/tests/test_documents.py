import os
from datetime import datetime, timezone
from pathlib import Path

import pytest

from ragkb.core.config import Config
from ragkb.core.errors import EngineUnavailable, InvalidRequest, NotFound, PayloadTooLarge
from ragkb.core.pipeline import RAGPipeline, build_index
from ragkb.services.documents import MAX_UPLOAD_BYTES, DocumentsService


def make_cfg(tmp_path: Path) -> Config:
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "policy.md").write_text(
        "# Политика\n\n## Отпуск\n\nЕжегодный отпуск составляет 28 календарных дней.\n",
        encoding="utf-8",
    )
    cfg = Config(docs_dir=str(docs), index_dir=str(tmp_path / "index"))
    cfg.store.backend = "numpy"
    return cfg


def make_service(cfg: Config) -> DocumentsService:
    def get_engine():
        try:
            return RAGPipeline(cfg)
        except (FileNotFoundError, ValueError) as exc:
            raise EngineUnavailable(str(exc)) from exc

    return DocumentsService(cfg, get_engine, lambda: None)


def test_list_after_build(tmp_path):
    cfg = make_cfg(tmp_path)
    build_index(cfg)
    svc = make_service(cfg)
    body = svc.list_documents()
    assert body["index"] == "ok"
    assert body["built_at"] is not None
    assert len(body["corpus"]) == 1
    row = body["corpus"][0]
    assert row["name"] == "policy.md"
    assert row["indexed"] is True
    assert row["state"] == "indexed"
    assert row["chunks"] >= 1
    assert body["summary"]["corpus_files"] == 1
    assert body["orphans"] == []


def test_list_new_file_is_new(tmp_path):
    cfg = make_cfg(tmp_path)
    build_index(cfg)
    (Path(cfg.docs_dir) / "fresh.md").write_text("# Новый\n\nТекст.\n", encoding="utf-8")
    body = make_service(cfg).list_documents()
    by_name = {r["name"]: r for r in body["corpus"]}
    assert by_name["fresh.md"]["state"] == "new"
    assert by_name["fresh.md"]["indexed"] is False


def test_list_stale_when_mtime_newer(tmp_path):
    cfg = make_cfg(tmp_path)
    build_index(cfg)
    target = Path(cfg.docs_dir) / "policy.md"
    future = datetime.now(timezone.utc).timestamp() + 3600
    os.utime(target, (future, future))
    body = make_service(cfg).list_documents()
    row = next(r for r in body["corpus"] if r["name"] == "policy.md")
    assert row["state"] == "stale"


def test_list_orphan_when_file_removed(tmp_path):
    cfg = make_cfg(tmp_path)
    build_index(cfg)
    (Path(cfg.docs_dir) / "policy.md").unlink()
    body = make_service(cfg).list_documents()
    assert len(body["orphans"]) == 1
    assert body["orphans"][0]["source"].endswith("policy.md")


def test_list_no_index(tmp_path):
    cfg = make_cfg(tmp_path)  # индекс не собран
    body = make_service(cfg).list_documents()
    assert body["index"] == "no_index"
    assert body["built_at"] is None
    assert body["orphans"] == [] and body["skipped"] == []
    assert body["corpus"][0]["state"] is None


def test_upload_saves_file_and_reindexes(tmp_path):
    cfg = make_cfg(tmp_path)
    build_index(cfg)
    svc = make_service(cfg)
    report = svc.upload("new.md", "# Новый\n\nПравило про отпуск: 28 дней.\n".encode())
    assert report["files"] >= 1
    assert (Path(cfg.docs_dir) / "new.md").exists()
    body = svc.list_documents()
    assert len(body["corpus"]) == 2
    assert all(r["indexed"] for r in body["corpus"])


def test_upload_rejects_bad_extension(tmp_path):
    cfg = make_cfg(tmp_path)
    svc = make_service(cfg)
    with pytest.raises(InvalidRequest):
        svc.upload("evil.exe", b"x" * 10)


def test_upload_rejects_hidden_name(tmp_path):
    cfg = make_cfg(tmp_path)
    svc = make_service(cfg)
    with pytest.raises(InvalidRequest):
        svc.upload(".env", b"SECRET=1\n")


def test_upload_rolls_back_when_corpus_empty(tmp_path, monkeypatch):
    cfg = make_cfg(tmp_path)
    (Path(cfg.docs_dir) / "policy.md").unlink()
    svc = make_service(cfg)
    # файл с расширением, но без текста — build_index упадёт целиком
    with pytest.raises(InvalidRequest):
        svc.upload("scan.pdf", b"%PDF-1.4 no text layer")
    assert not (Path(cfg.docs_dir) / "scan.pdf").exists()


def test_upload_size_limit(tmp_path):
    cfg = make_cfg(tmp_path)
    svc = make_service(cfg)
    with pytest.raises(PayloadTooLarge):
        svc.upload("big.md", b"a" * (MAX_UPLOAD_BYTES + 1))


def test_delete_removes_file_and_index_entry(tmp_path):
    cfg = make_cfg(tmp_path)
    build_index(cfg)
    (Path(cfg.docs_dir) / "policy.md").write_text(
        "# A\n\n## B\n\n" + "x" * 2000 + "\n", encoding="utf-8"
    )
    # второй документ, чтобы после удаления корпус не опустел
    (Path(cfg.docs_dir) / "keep.md").write_text("# Keep\n\nТекст для чанка.\n", encoding="utf-8")
    build_index(cfg)
    svc = make_service(cfg)
    svc.delete("policy.md")
    assert not (Path(cfg.docs_dir) / "policy.md").exists()
    body = svc.list_documents()
    names = {r["name"] for r in body["corpus"]}
    assert "policy.md" not in names and "keep.md" in names


def test_delete_missing_file_is_404(tmp_path):
    cfg = make_cfg(tmp_path)
    build_index(cfg)
    with pytest.raises(NotFound):
        make_service(cfg).delete("nope.md")


def test_delete_last_doc_clears_index(tmp_path):
    cfg = make_cfg(tmp_path)
    build_index(cfg)
    make_service(cfg).delete("policy.md")
    body = make_service(cfg).list_documents()
    assert body["index"] == "no_index"


def test_delete_on_chroma_is_point_removal(tmp_path):
    pytest.importorskip("chromadb")
    cfg = make_cfg(tmp_path)
    cfg.store.backend = "chroma"
    build_index(cfg)
    (Path(cfg.docs_dir) / "keep.md").write_text("# Keep\n\nТекст.\n", encoding="utf-8")
    build_index(cfg)
    make_service(cfg).delete("keep.md")
    body = make_service(cfg).list_documents()
    assert all(r["name"] != "keep.md" for r in body["corpus"])


def test_delete_last_doc_clears_chroma_index(tmp_path):
    pytest.importorskip("chromadb")
    cfg = make_cfg(tmp_path)
    cfg.store.backend = "chroma"
    build_index(cfg)
    make_service(cfg).delete("policy.md")
    body = make_service(cfg).list_documents()
    assert body["index"] == "no_index"
