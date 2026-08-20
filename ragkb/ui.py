"""Разметка веб-интерфейса.

Вынесена из api.py отдельным модулем: чат со списком диалогов и разбором
потока утроил размер константы, и она стала крупнее самого модуля, который
отвечает за HTTP, а не за интерфейс.

Модуль, а не файл .html рядом: в pyproject.toml не настроены данные пакета,
и файл, не являющийся .py, не попал бы в дистрибутив без правки упаковки.
"""

UI_HTML = """<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>База знаний</title>
<style>
  :root {
    --bg:#fff; --fg:#1a1a1a; --muted:#6b7280; --line:#e5e7eb;
    --accent:#2563eb; --card:#f9fafb; --side:#f3f4f6;
  }
  @media (prefers-color-scheme: dark) {
    :root { --bg:#0f1115; --fg:#e8eaed; --muted:#9aa0a6; --line:#2a2f37;
            --accent:#60a5fa; --card:#171a21; --side:#12151b; }
  }
  * { box-sizing:border-box; }
  body { margin:0; height:100vh; display:flex; background:var(--bg); color:var(--fg);
         font:15px/1.6 -apple-system,"Segoe UI",Roboto,Helvetica,sans-serif; }

  aside { width:260px; flex:none; border-right:1px solid var(--line);
          background:var(--side); display:flex; flex-direction:column; }
  aside h1 { font-size:15px; margin:0; padding:14px 16px 10px; }
  #new { margin:0 12px 10px; padding:8px; border:1px solid var(--line);
         border-radius:8px; background:var(--bg); color:var(--fg); cursor:pointer; }
  #list { flex:1; overflow-y:auto; padding:0 8px 12px; }
  .conv { display:flex; align-items:center; gap:6px; padding:8px 10px;
          border-radius:8px; cursor:pointer; }
  .conv:hover { background:var(--card); }
  .conv.active { background:var(--card); outline:1px solid var(--line); }
  .conv .t { flex:1; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
  .conv .d { color:var(--muted); font-size:12px; }
  .del { border:0; background:none; color:var(--muted); cursor:pointer;
         font-size:16px; line-height:1; padding:0 2px; }
  .del:hover { color:#dc2626; }

  main { flex:1; display:flex; flex-direction:column; min-width:0; }
  #status { color:var(--muted); font-size:13px; padding:14px 20px 6px; }
  #thread { flex:1; overflow-y:auto; padding:8px 20px 20px; }
  .msg { margin-bottom:18px; max-width:760px; }
  .msg.user .who { color:var(--accent); }
  .who { font-size:12px; text-transform:uppercase; letter-spacing:.05em;
         color:var(--muted); margin-bottom:4px; }
  .body { white-space:pre-wrap; }
  .msg.assistant .body { padding:14px 16px; background:var(--card);
         border:1px solid var(--line); border-radius:10px; }
  .src { font-size:13px; color:var(--muted); margin-top:8px; }
  .src .gone { color:#b45309; }
  .warn { color:#b45309; font-size:13px; margin-top:6px; }
  .meta { color:var(--muted); font-size:12px; margin-top:6px; }
  .empty { color:var(--muted); padding:40px 0; text-align:center; }

  form { display:flex; gap:8px; padding:12px 20px 18px; border-top:1px solid var(--line); }
  #q { flex:1; padding:11px 13px; font-size:15px; border-radius:8px;
       border:1px solid var(--line); background:var(--bg); color:var(--fg); }
  #q:focus { outline:2px solid var(--accent); outline-offset:-1px; border-color:transparent; }
  #send { padding:11px 20px; border:0; border-radius:8px; background:var(--accent);
          color:#fff; cursor:pointer; }
  #send:disabled { opacity:.5; cursor:default; }

  #controls { display:flex; gap:16px; padding:8px 20px 0; font-size:13px;
              color:var(--muted); }
  #controls select { background:var(--bg); color:var(--fg);
              border:1px solid var(--line); border-radius:6px; padding:3px 6px; }

  @media (max-width:760px) {
    body { flex-direction:column; height:auto; min-height:100vh; }
    aside { width:auto; border-right:0; border-bottom:1px solid var(--line); max-height:38vh; }
  }
</style>
</head>
<body>
<aside>
  <h1>База знаний</h1>
  <button id="new">Новый диалог</button>
  <div id="list"></div>
  <div style="padding:10px 16px"><a href="/oauth2/sign_out">выйти</a></div>
</aside>
<main>
  <div id="status">загрузка…</div>
  <div id="thread"></div>
  <div id="controls">
    <label id="model-box">Модель <select id="model"></select></label>
    <span id="search-mode" style="display:none">Моделей нет — ответы собираются из найденных фрагментов</span>
    <label>Фрагментов <select id="topk">
      <option value="" selected>по умолчанию</option>
      <option value="2">2</option>
      <option value="3">3</option>
      <option value="5">5</option>
    </select></label>
  </div>
  <form id="f">
    <input type="text" id="q" placeholder="Задайте вопрос по документам…"
           autocomplete="off" autofocus>
    <button type="submit" id="send">Спросить</button>
  </form>
</main>
<script>
const listEl = document.getElementById('list');
const threadEl = document.getElementById('thread');
const qEl = document.getElementById('q');
const sendEl = document.getElementById('send');

let currentId = null;   // единственное состояние на клиенте
let streaming = false;  // идёт поток ответа — переключать/удалять диалоги нельзя

const modelEl = document.getElementById('model');
const topkEl = document.getElementById('topk');

// Выбор помнит браузер: сервер намеренно без состояния везде, кроме истории.
function restoreChoice() {
  const m = localStorage.getItem('ragkb.model');
  const k = localStorage.getItem('ragkb.topk');
  if (m) {
    // Вариант по умолчанию уже выбран (loadModels отметил m.default) —
    // запоминаем его на случай, если сохранённая модель промахнётся.
    const fallback = modelEl.selectedIndex;
    modelEl.value = m;
    // Сохранённая модель могла пропасть из конфигурации — тогда value
    // промахивается, selectedIndex становится -1, и поле выглядит пустым.
    // Оставляем вариант по умолчанию и чистим протухшую запись.
    if (modelEl.selectedIndex < 0) {
      modelEl.selectedIndex = fallback;
      localStorage.removeItem('ragkb.model');
    }
  }
  if (k) {
    const fallback = topkEl.selectedIndex;
    topkEl.value = k;
    if (topkEl.selectedIndex < 0) {
      topkEl.selectedIndex = fallback;
      localStorage.removeItem('ragkb.topk');
    }
  }
}
modelEl.addEventListener('change', () => localStorage.setItem('ragkb.model', modelEl.value));
topkEl.addEventListener('change', () => localStorage.setItem('ragkb.topk', topkEl.value));

async function loadModels() {
  try {
    const r = await fetch('/models');
    if (!r.ok) return;
    const items = (await r.json()).models || [];
    // Моделей нет вовсе — сервис отвечает найденными фрагментами.
    // Прятать выбор честнее, чем показывать пустой список.
    if (!items.length) {
      document.getElementById('model-box').style.display = 'none';
      document.getElementById('search-mode').style.display = '';
      return;
    }
    modelEl.innerHTML = '';
    items.forEach(m => {
      const o = document.createElement('option');
      o.value = m.id;
      o.textContent = m.id;
      if (m.is_default) o.selected = true;
      modelEl.appendChild(o);
    });
    restoreChoice();
  } catch (_) { /* список моделей не критичен: без него работает выбор по умолчанию */ }
}

function esc(s) {
  return String(s).replace(/[&<>"]/g, c =>
    ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
}

function shortDate(iso) {
  if (!iso) return '';
  const d = new Date(iso);
  return isNaN(d) ? '' : d.toLocaleDateString('ru-RU', {day:'2-digit', month:'2-digit'});
}

fetch('/health').then(r => r.json()).then(d => {
  document.getElementById('status').textContent = d.status === 'ok'
    ? `${d.documents} документов · ${d.chunks} фрагментов · ${d.embedder} · ${d.llm}`
    : 'Индекс не построен';
}).catch(() => {});

async function loadList() {
  const r = await fetch('/conversations');
  if (!r.ok) { listEl.innerHTML = ''; warn(threadEl, 'Не удалось загрузить список диалогов'); return []; }
  const items = (await r.json()).conversations || [];
  listEl.innerHTML = '';
  items.forEach(c => {
    const row = document.createElement('div');
    row.className = 'conv' + (c.id === currentId ? ' active' : '');
    row.innerHTML = `<span class="t">${esc(c.title || 'Без названия')}</span>` +
                    `<span class="d">${shortDate(c.updated_at)}</span>` +
                    `<button class="del" title="Удалить">×</button>`;
    row.querySelector('.t').onclick = () => openConv(c.id);
    row.querySelector('.d').onclick = () => openConv(c.id);
    row.querySelector('.del').onclick = e => { e.stopPropagation(); removeConv(c.id, c.title); };
    listEl.appendChild(row);
  });
  return items;
}

function renderSources(sources) {
  if (!sources || !sources.length) return '';
  const rows = sources.map(s => {
    // available отсутствует — состав индекса неизвестен, пометку не ставим.
    const gone = s.available === false
      ? ' <span class="gone">(источник больше не в базе)</span>' : '';
    return `[${esc(s.n)}] ${esc(s.citation)}${gone}`;
  });
  return `<div class="src">${rows.join('<br>')}</div>`;
}

function addMessage(role, text, sources) {
  const el = document.createElement('div');
  el.className = 'msg ' + role;
  el.innerHTML = `<div class="who">${role === 'user' ? 'Вы' : 'Ассистент'}</div>` +
                 `<div class="body"></div>`;
  el.querySelector('.body').textContent = text || '';
  threadEl.appendChild(el);
  if (sources) el.insertAdjacentHTML('beforeend', renderSources(sources));
  threadEl.scrollTop = threadEl.scrollHeight;
  return el;
}

function renderModelMeta(model) {
  return model ? `<div class="meta">${esc(model)}</div>` : '';
}

function warn(container, text) {
  container.insertAdjacentHTML('beforeend', `<div class="warn">⚠ ${esc(text)}</div>`);
}

async function openConv(id) {
  if (streaming) return;
  const r = await fetch('/conversations/' + encodeURIComponent(id));
  if (!r.ok) {
    threadEl.innerHTML = '';
    warn(threadEl, 'Не удалось открыть диалог');
    return;
  }
  const data = await r.json();
  currentId = data.id;
  threadEl.innerHTML = '';
  (data.messages || []).forEach(m => {
    const el = addMessage(m.role, m.text, m.sources);
    if (m.role === 'assistant' && m.model) el.insertAdjacentHTML('beforeend', renderModelMeta(m.model));
  });
  await loadList();
}

async function startNew() {
  if (streaming) return;
  currentId = null;
  threadEl.innerHTML = '<div class="empty">Задайте вопрос по документам</div>';
  await loadList();
  qEl.focus();
}

async function removeConv(id, title) {
  if (streaming) return;
  if (!confirm(`Удалить диалог «${title || 'Без названия'}»? Восстановить нельзя.`)) return;
  const r = await fetch('/conversations/' + encodeURIComponent(id), {method:'DELETE'});
  if (!r.ok) { warn(threadEl, 'Не удалось удалить диалог'); return; }
  if (id === currentId) {
    const rest = await loadList();
    if (rest.length) await openConv(rest[0].id); else await startNew();
  } else {
    await loadList();
  }
}

document.getElementById('new').onclick = () => startNew();

document.getElementById('f').addEventListener('submit', async e => {
  e.preventDefault();
  if (streaming) return;
  const question = qEl.value.trim();
  if (!question) return;
  qEl.value = '';
  sendEl.disabled = true;
  streaming = true;

  if (threadEl.querySelector('.empty')) threadEl.innerHTML = '';
  addMessage('user', question);
  const box = addMessage('assistant', '');
  const bodyEl = box.querySelector('.body');
  bodyEl.textContent = '…';
  let finished = false;   // выставляется по 'done' или 'error' от сервера

  try {
    const resp = await fetch('/ask/stream', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({
        question,
        conversation_id: currentId,
        model: modelEl.value || null,
        // Пустое значение — «по умолчанию»: top_k вовсе не кладём в запрос,
        // тогда работает retrieval.top_k из конфигурации сервера.
        top_k: topkEl.value ? parseInt(topkEl.value, 10) : null
      })
    });
    if (!resp.ok) {
      if (resp.status === 404) {
        // Диалог убрали (другая вкладка, уборка по сроку хранения) —
        // без сброса currentId все следующие вопросы будут падать так же.
        currentId = null;
        await loadList();
        bodyEl.textContent = '';
        warn(box, 'Диалог не найден, начат новый');
      } else {
        bodyEl.textContent = 'Ошибка: ' + resp.status;
      }
      return;
    }
    const reader = resp.body.getReader();
    const decoder = new TextDecoder();
    let buf = '', text = '';
    while (true) {
      const {done, value} = await reader.read();
      if (done) break;
      buf += decoder.decode(value, {stream: true});
      let nl;
      while ((nl = buf.indexOf('\\n')) >= 0) {
        const line = buf.slice(0, nl).trim();
        buf = buf.slice(nl + 1);
        if (!line) continue;
        let ev;
        try { ev = JSON.parse(line); } catch (_) { continue; }
        if (ev.type === 'token') {
          text += ev.text;
          bodyEl.textContent = text;
          threadEl.scrollTop = threadEl.scrollHeight;
        } else if (ev.type === 'error') {
          // Статус уже 200 — об отказе сообщает событие, и его надо показать,
          // иначе обрыв выглядит зависшим ответом.
          finished = true;
          bodyEl.textContent = text || '';
          warn(box, 'Ошибка генерации: ' + ev.detail);
          return;
        } else if (ev.type === 'done') {
          finished = true;
          currentId = ev.conversation_id || currentId;
          if (!text.trim()) {
            box.insertAdjacentHTML('beforeend',
              '<div class="warn">⚠ Модель вернула пустой ответ</div>');
          }
          box.insertAdjacentHTML('beforeend', renderSources(ev.sources));
          (ev.warnings || []).forEach(w => warn(box, w));
          const label = ev.model ? `${esc(ev.model)} · ${esc(ev.elapsed_sec)} с`
                                 : `${esc(ev.elapsed_sec)} с`;
          box.insertAdjacentHTML('beforeend', `<div class="meta">${label}</div>`);
          await loadList();
        }
      }
    }
    if (!finished) {
      // Чтение закончилось (реже — соединение оборвалось), но ни 'done',
      // ни 'error' от сервера не пришло: без этого текст выглядел бы
      // законченным ответом без источников и без предупреждения.
      bodyEl.textContent = text || '';
      warn(box, 'Ответ оборван, соединение прервано');
    }
  } catch (err) {
    bodyEl.textContent = 'Ошибка: ' + err.message;
  } finally {
    streaming = false;
    sendEl.disabled = false;
    qEl.focus();
  }
});

(async () => {
  await loadModels();
  const items = await loadList();
  if (items.length) await openConv(items[0].id); else await startNew();
})();
</script>
</body>
</html>"""
