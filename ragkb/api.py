"""HTTP API на FastAPI + минимальный веб-интерфейс."""
from __future__ import annotations

from typing import Any

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import HTMLResponse, StreamingResponse
from pydantic import BaseModel, Field

from .auth import User, current_user, optional_user, require_admin
from .config import Config
from .pipeline import RAGPipeline, build_index


class AskRequest(BaseModel):
    question: str = Field(..., min_length=2)
    top_k: int | None = None
    expand: bool = False
    history: list[tuple[str, str]] = Field(default_factory=list)


class SearchRequest(BaseModel):
    query: str = Field(..., min_length=2)
    top_k: int = 5


def create_app(cfg: Config) -> FastAPI:
    app = FastAPI(title="RAG База знаний", version="1.0")

    # Зависимости идентификации читают настройки отсюда.
    app.state.auth = cfg.auth
    if cfg.auth.mode == "disabled":
        print(
            "ВНИМАНИЕ: аутентификация выключена (auth.mode: disabled). "
            "Все запросы выполняются от имени «anonymous». "
            "В общем контуре так работать нельзя."
        )

    state: dict[str, Any] = {"pipeline": None, "error": None}

    def pipeline() -> RAGPipeline:
        if state["pipeline"] is None:
            try:
                state["pipeline"] = RAGPipeline(cfg)
                state["error"] = None
            except Exception as exc:
                state["error"] = str(exc)
                raise HTTPException(status_code=503, detail=str(exc))
        return state["pipeline"]

    @app.get("/health")
    def health() -> dict[str, Any]:
        try:
            return {"status": "ok", **pipeline().stats()}
        except HTTPException as exc:
            return {"status": "no_index", "detail": exc.detail}

    @app.post("/ask")
    def ask(req: AskRequest, user: User = Depends(current_user)) -> dict[str, Any]:
        answer = pipeline().ask(
            req.question,
            top_k=req.top_k,
            history=[tuple(h) for h in req.history] or None,
            expand=req.expand,
        )
        return answer.to_dict()

    @app.post("/ask/stream")
    def ask_stream(req: AskRequest, user: User = Depends(current_user)) -> StreamingResponse:
        rag = pipeline()

        def generate():
            for piece in rag.stream_answer(req.question, top_k=req.top_k):
                yield piece

        return StreamingResponse(generate(), media_type="text/plain; charset=utf-8")

    @app.post("/search")
    def search(req: SearchRequest, user: User = Depends(current_user)) -> dict[str, Any]:
        hits = pipeline().search(req.query, top_k=req.top_k)
        return {"query": req.query, "results": [h.to_dict() for h in hits]}

    @app.post("/reindex")
    def reindex() -> dict[str, Any]:
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


UI_HTML = """<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>База знаний</title>
<style>
  :root {
    --bg: #ffffff; --fg: #1a1a1a; --muted: #6b7280; --line: #e5e7eb;
    --accent: #2563eb; --card: #f9fafb;
  }
  @media (prefers-color-scheme: dark) {
    :root { --bg:#0f1115; --fg:#e8eaed; --muted:#9aa0a6; --line:#2a2f37;
            --accent:#60a5fa; --card:#171a21; }
  }
  * { box-sizing: border-box; }
  body { margin:0; background:var(--bg); color:var(--fg); font:16px/1.6
         -apple-system, "Segoe UI", Roboto, Helvetica, sans-serif; }
  .wrap { max-width: 780px; margin: 0 auto; padding: 32px 20px 80px; }
  h1 { font-size: 20px; font-weight: 600; margin: 0 0 4px; }
  .sub { color: var(--muted); font-size: 14px; margin-bottom: 24px; }
  form { display: flex; gap: 8px; margin-bottom: 24px; }
  input[type=text] { flex:1; padding:12px 14px; font-size:15px; border-radius:8px;
    border:1px solid var(--line); background:var(--bg); color:var(--fg); }
  input[type=text]:focus { outline:2px solid var(--accent); outline-offset:-1px; border-color:transparent; }
  button { padding:12px 20px; font-size:15px; border:0; border-radius:8px;
    background:var(--accent); color:#fff; cursor:pointer; }
  button:disabled { opacity:.5; cursor:default; }
  .answer { white-space: pre-wrap; padding:18px; background:var(--card);
    border:1px solid var(--line); border-radius:10px; margin-bottom:20px; }
  .sources { font-size:14px; }
  .sources h2 { font-size:13px; text-transform:uppercase; letter-spacing:.05em;
    color:var(--muted); margin:24px 0 10px; font-weight:600; }
  details { border:1px solid var(--line); border-radius:8px; padding:10px 14px;
    margin-bottom:8px; background:var(--card); }
  summary { cursor:pointer; font-weight:500; }
  .frag { color:var(--muted); font-size:14px; margin-top:8px; white-space:pre-wrap; }
  .meta { color:var(--muted); font-size:13px; margin-top:20px; }
  .warn { color:#b45309; font-size:14px; margin-top:10px; }
  .spin { color:var(--muted); }
</style>
</head>
<body>
<div class="wrap">
  <h1>База знаний</h1>
  <div class="sub" id="status">загрузка…</div>
  <form id="f">
    <input type="text" id="q" placeholder="Задайте вопрос по документам…" autocomplete="off" autofocus>
    <button type="submit" id="btn">Спросить</button>
  </form>
  <div id="out"></div>
</div>
<script>
const out = document.getElementById('out');
const btn = document.getElementById('btn');

fetch('/health').then(r => r.json()).then(d => {
  document.getElementById('status').textContent = d.status === 'ok'
    ? `${d.documents} документов · ${d.chunks} фрагментов · ${d.embedder} · ${d.llm}`
    : 'Индекс не построен: ' + (d.detail || '');
});

document.getElementById('f').addEventListener('submit', async (e) => {
  e.preventDefault();
  const question = document.getElementById('q').value.trim();
  if (!question) return;
  btn.disabled = true;
  out.innerHTML = '<div class="spin">Ищу…</div>';
  try {
    const res = await fetch('/ask', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({question})
    });
    const data = await res.json();
    render(data);
  } catch (err) {
    out.innerHTML = '<div class="warn">Ошибка: ' + err.message + '</div>';
  } finally {
    btn.disabled = false;
  }
});

function esc(s) {
  return String(s).replace(/[&<>"]/g, c =>
    ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
}

function render(d) {
  let html = '<div class="answer">' + esc(d.answer) + '</div>';
  if (d.sources && d.sources.length) {
    html += '<div class="sources"><h2>Источники</h2>';
    d.sources.forEach(s => {
      html += `<div>[${s.n}] ${esc(s.citation)}</div>`;
    });
    html += '</div>';
  }
  if (d.chunks && d.chunks.length) {
    html += '<div class="sources"><h2>Найденные фрагменты</h2>';
    d.chunks.forEach((c, i) => {
      html += `<details><summary>[${i+1}] ${esc(c.citation)} · ${c.score}</summary>
               <div class="frag">${esc(c.text)}</div></details>`;
    });
    html += '</div>';
  }
  (d.warnings || []).forEach(w => { html += '<div class="warn">⚠ ' + esc(w) + '</div>'; });
  html += `<div class="meta">${d.elapsed_sec} с · ${esc(d.llm)}</div>`;
  out.innerHTML = html;
}
</script>
</body>
</html>"""
