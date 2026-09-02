# Admin closeout Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Закрыть админку в живых доках и спеках и подтвердить sqlite-тестами плюс локальным UI, без новых ручек.

**Architecture:** Код ролей / сидера / `/admin/*` уже на `main`. Этот план меняет статусы спек и текст `README.md` (и `AGENTS.md` только если он снова расходится с Makefile). Проверка — существующие pytest на sqlite и ручной проход UI. Код приложения — только если UI покажет баг в уже слитом поведении.

**Tech Stack:** Markdown, pytest, Make, SvelteKit UI, sqlite `data/ragkb.sqlite3`.

**Спека:** `docs/superpowers/specs/2026-09-02-admin-closeout-design.md`

## Global Constraints

- Не добавлять HTTP-ручек и страниц.
- Не закрывать публичный `/auth/signup` и `/register`.
- Не деплоить на сервер.
- Не чинить `bun run check`.
- Не переписывать `docs/superpowers/plans/` кроме **этого нового** файла (исторические планы — слепок).
- Не трогать `docs/superpowers/specs/2026-08-19-identity-and-history-design.md`.
- Не трогать `frontend/README.md` (там `ragkb-admins` для режима `proxy`).
- Полный `pytest` с Postgres не блокер: если нет `RAGKB_TEST_DATABASE_URL` — не останавливаться.
- Коммит после каждой задачи. Не пушить, пока не попросят.
- Код `backend/` / `frontend/src` не менять, пока проход UI не покажет баг.

## File map

**Создать**

- нет

**Менять**

- `docs/superpowers/specs/2026-09-02-admin-users-design.md` — статус готово
- `docs/superpowers/specs/2026-09-01-local-auth-design.md` — статус готово + одна фраза про роль
- `README.md` — rebuild, `make backend`, чеклист оператора
- `AGENTS.md` — только если `rg` найдёт противоречие с Makefile (`disabled` для `make backend`)
- `docs/superpowers/specs/2026-09-02-admin-closeout-design.md` — статус готово после проверки

---

### Task 1: Статусы спек admin-users и local-auth

**Files:**
- Modify: `docs/superpowers/specs/2026-09-02-admin-users-design.md`
- Modify: `docs/superpowers/specs/2026-09-01-local-auth-design.md`

**Interfaces:**
- Consumes: ничего
- Produces: обе спеки со статусом `готово`; в local-auth абзац про соседнюю спеку ролей

- [ ] **Step 1: Зафиксировать текущий статус (ожидаем «в работе»)**

Run from repo root:

```bash
rg -n "Статус" docs/superpowers/specs/2026-09-02-admin-users-design.md docs/superpowers/specs/2026-09-01-local-auth-design.md
```

Expected: строки `| Статус | в работе |` в обоих файлах.

- [ ] **Step 2: Поставить статус готово в admin-users**

В `docs/superpowers/specs/2026-09-02-admin-users-design.md` заменить только ячейку статуса:

```
| Статус | готово |
```

Не менять остальные разделы этой спеки.

- [ ] **Step 3: Поставить статус готово и одну фразу в local-auth**

В `docs/superpowers/specs/2026-09-01-local-auth-design.md`:

1. Заменить `| Статус | в работе |` на `| Статус | готово |`.
2. Сразу после абзаца

```
«Перестроить индекс» по-прежнему требует группу `ragkb-admins` в объекте
`User`. У локального пользователя групп нет — кнопки не будет, пока отдельная
работа не задаст роль.
```

вставить (не удаляя этот абзац):

```
Роль админа в `session` и кнопка переиндексации закрыты спекой
`2026-09-02-admin-users`.
```

Блок **Вне работы** той спеки целиком не переписывать.

- [ ] **Step 4: Проверить статусы**

```bash
rg -n "Статус" docs/superpowers/specs/2026-09-02-admin-users-design.md docs/superpowers/specs/2026-09-01-local-auth-design.md
rg -n "2026-09-02-admin-users" docs/superpowers/specs/2026-09-01-local-auth-design.md
```

Expected: `| Статус | готово |` в обоих; в local-auth есть строка со спекой `2026-09-02-admin-users`.

- [ ] **Step 5: Commit**

```bash
git add docs/superpowers/specs/2026-09-02-admin-users-design.md docs/superpowers/specs/2026-09-01-local-auth-design.md
git commit -m "Mark local-auth and admin-users specs done."
```

---

### Task 2: Живые доки README и AGENTS

**Files:**
- Modify: `README.md`
- Modify: `AGENTS.md` (только если Step 2 найдёт расхождение)

**Interfaces:**
- Consumes: Task 1 (спеки готовы; на текст README не влияет)
- Produces: README без «rebuild только ragkb-admins» для session; `make backend` = session + SQLite; чеклист оператора `ADMIN_*`

- [ ] **Step 1: Показать расхождения (ожидаем совпадения с текущим README)**

```bash
rg -n "ragkb-admins|make backend|ADMIN_LOGIN" README.md AGENTS.md Makefile
```

Expected before edit: в `README.md` есть `| \`POST /index/rebuild\` | переиндексация, только \`ragkb-admins\` |` и пункт списка `` `make backend` — `RAGKB_AUTH_MODE=disabled` ``. В `AGENTS.md` уже `make backend` — SQLite и `auth.mode: session`. В `Makefile` `backend` экспортирует `RAGKB_AUTH_MODE` default `session`.

- [ ] **Step 2: AGENTS.md**

Если `rg "disabled" AGENTS.md` не описывает `make backend` как `disabled` — **не редактировать** `AGENTS.md`.

Если описывает — заменить описание запуска на тот же смысл, что в Makefile:

```
`make backend` — SQLite `data/ragkb.sqlite3`, `auth.mode: session` (Postgres не нужен). Compose остаётся на Postgres.
```

- [ ] **Step 3: README — быстрый старт и make backend**

В блоке «Быстрый старт» заменить комментарий и два `export` `disabled` / `HISTORY_ENABLED=false` на отсылку к Make. Итоговый фрагмент:

```bash
cd backend
uv sync --extra migrations --extra dev

# схема истории (нужен Postgres и RAGKB_DATABASE_URL)
alembic upgrade head

# индекс — POST /index/rebuild (кнопка в интерфейсе у администратора)
# локально с формами и SQLite (без Postgres):
make backend

# в другом терминале — интерфейс
cd ../frontend
bun install
RAGKB_BACKEND_URL=http://127.0.0.1:8000 bun run dev
```

В «Боевая конфигурация» заменить пункт списка

```
- `make backend` — `RAGKB_AUTH_MODE=disabled` и `RAGKB_HISTORY_ENABLED=false`
  (anonymous, без форм и без Postgres).
```

на:

```
- `make backend` — `RAGKB_AUTH_MODE=session` и SQLite `data/ragkb.sqlite3`
  (формы `/login` и `/register`, Postgres не нужен).
```

- [ ] **Step 4: README — rebuild и чеклист оператора**

Строку таблицы HTTP заменить на:

```
| `POST /index/rebuild` | переиндексация: в `session` роль `admin`; в `proxy` группа `auth.admin_group` (по умолчанию `ragkb-admins`) |
```

Сразу после существующего абзаца

```
`ADMIN_LOGIN` / `ADMIN_PASSWORD` (8–128 символов) — одноразовый compose-сервис
`ensure-admin` после migrate создаёт или обновляет админа. Оба пустые — сидер
пропускается.
```

добавить чеклист оператора (деплой в этом заходе не выполнять):

```
Чеклист оператора (сервер, не часть `make backend`):

- в `.env` на сервере задать оба `ADMIN_LOGIN` и `ADMIN_PASSWORD`;
- `docker compose up` / `make up` должен запускать сервис `ensure-admin` после `migrate`;
- оба значения пустые — сидер выходит 0, пользователя-админа нет;
- после подъёма войти этим логином и открыть `/admin`.
```

Не удалять блок `.env` с примером `ADMIN_LOGIN=admin`.

- [ ] **Step 5: Проверить доки**

```bash
rg -n "RAGKB_AUTH_MODE=disabled" README.md
rg -n "только \`ragkb-admins\`" README.md
rg -n "роль \`admin\`" README.md
rg -n "Чеклист оператора" README.md
```

Expected: первая и вторая команды — нет совпадений (или disabled только вне описания `make backend`). Третья и четвёртая — есть совпадения. `frontend/README.md` не в `git diff`.

- [ ] **Step 6: Commit**

```bash
git add README.md
# git add AGENTS.md  — только если файл меняли
git commit -m "Align README with session admin role and make backend."
```

---

### Task 3: Sqlite-тесты админки

**Files:**
- Test (только запуск): `backend/tests/test_architecture.py`
- Test: `backend/tests/test_admin_credentials.py`
- Test: `backend/tests/test_ensure_admin.py`
- Test: `backend/tests/test_admin_http.py`
- Test: `backend/tests/test_guard.py`

**Interfaces:**
- Consumes: код админки уже на `main`; Task 2 не меняет тесты
- Produces: зелёный прогон sqlite-набора без Postgres

- [ ] **Step 1: Запуск**

```bash
cd backend && uv run pytest tests/test_architecture.py tests/test_admin_credentials.py tests/test_ensure_admin.py tests/test_admin_http.py tests/test_guard.py -q
```

Expected: exit 0, все тесты PASS. Не включать `tests/test_session_auth.py` (часть фикстур требует Postgres).

Если нет `RAGKB_TEST_DATABASE_URL` — **не** гонять полный `uv run pytest` как блокер. Если URL задан — можно дополнительно `cd backend && uv run pytest -q`; падение полного набора без URL не чинить в этом заходе.

- [ ] **Step 2: Commit только если меняли код из-за падения**

Если Step 1 зелёный и код не трогали — коммит не создавать.

Если падение из-за бага в приложении — минимальный фикс + тот же pytest + commit:

```bash
git commit -m "Fix admin sqlite tests after closeout check."
```

Не ослаблять ассерты, чтобы «пройти».

---

### Task 4: Локальный UI и статус closeout-спеки

**Files:**
- Modify: `docs/superpowers/specs/2026-09-02-admin-closeout-design.md` (статус готово после прохода)
- Code: только при баге UI (файлы по факту бага)

**Interfaces:**
- Consumes: sqlite URL как у `make backend`; `scripts.ensure_admin`; страницы `/admin`, `/admin/users`, `/admin/reports`; шапка «Админ»; `rebuildIndex` в `frontend/src/routes/+layout.svelte`
- Produces: проход UI записан; closeout-спека `готово`

- [ ] **Step 1: Поднять API**

Из корня репозитория (освободить порт 8000, если занят):

```bash
make backend
```

Expected: alembic upgrade на `sqlite+aiosqlite:///…/data/ragkb.sqlite3`, uvicorn `127.0.0.1:8000`.

- [ ] **Step 2: Сидер админа на том же SQLite**

В другом терминале, из `backend/`, с тем же файлом БД, что Makefile (`data/ragkb.sqlite3` в корне репо):

```bash
cd backend
ADMIN_LOGIN=admin ADMIN_PASSWORD=adminpass \
  RAGKB_DATABASE_URL="sqlite+aiosqlite:///$(cd .. && pwd)/data/ragkb.sqlite3" \
  uv run python -m scripts.ensure_admin
```

Expected: процесс exit 0; в логе создание админа или обновление хеша. Логин нормализуется в `admin`.

- [ ] **Step 3: Фронт**

```bash
cd frontend && bun install && RAGKB_BACKEND_URL=http://127.0.0.1:8000 bun run dev
```

Expected: SvelteKit на порту dev (обычно 5173). Браузер только в BFF, не на `:8000`.

- [ ] **Step 4: Проход UI**

Войти как `admin` / `adminpass`. Проверить:

1. В шапке ссылка «Админ».
2. `/admin` — хаб (название организации или «Организация», ссылки Пользователи и Отчёты).
3. `/admin/users` — таблица; смена роли существующего `user` (если есть только админ — зарегистрировать второго на `/register`, затем выдать/снять админа у него, не снимая последнего админа).
4. `/admin/reports` — текст, что отчёты позже / недоступны.
5. Кнопка «Перестроить индекс» в шапке чата (не на `/admin`): запрос уходит, не 403 для админа.

Не-админ: ссылки «Админ» нет; `/admin` редирект на `/new` или `/login`.

Баг в слитом поведении — фикс минимальный, снова sqlite pytest из Task 3, снова клик по сломанному шагу.

- [ ] **Step 5: Статус closeout-спеки**

В `docs/superpowers/specs/2026-09-02-admin-closeout-design.md` заменить `| Статус | в работе |` на `| Статус | готово |`.

```bash
rg -n "Статус" docs/superpowers/specs/2026-09-02-admin-closeout-design.md
```

Expected: `| Статус | готово |`.

- [ ] **Step 6: Commit**

Если менялись только спека closeout:

```bash
git add docs/superpowers/specs/2026-09-02-admin-closeout-design.md
git commit -m "Mark admin closeout spec done after local UI check."
```

Если чинили UI/бэкенд — включить те файлы в тот же или отдельный commit с сообщением про фикс, затем статус спеки.

Не пушить.

---

## Spec coverage

| Спека | Задача |
|---|---|
| статус admin-users готово | 1 |
| статус local-auth готово + фраза про роль | 1 |
| README rebuild session vs proxy | 2 |
| README make backend session + SQLite | 2 |
| чеклист оператора ADMIN_* | 2 |
| AGENTS без противоречия Makefile | 2 |
| sqlite pytest набор | 3 |
| UI хаб / люди / отчёты / шапка / rebuild | 4 |
| статус closeout готово | 4 |
| не деплой / не signup / не bun check / не планы | constraints |
