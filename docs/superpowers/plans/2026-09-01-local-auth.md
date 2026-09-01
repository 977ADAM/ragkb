# Local Auth Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Регистрация и вход логином/паролем в FastAPI, сессия в httpOnly-куке, формы и BFF в `frontend/`.

**Architecture:** Слайс `ragkb.features.auth`: синхронный адаптер `sqlite3` в том же файле, что история; Argon2; кука `ragkb_session`. `current_user` в режиме `session` читает только куку. BFF проксирует `/api/auth/*` и `Cookie`/`Set-Cookie`. Страницы `/login` и `/register`.

**Tech Stack:** Python 3.10+, FastAPI, sqlite3, Alembic, argon2-cffi, SvelteKit BFF.

**Спека:** `docs/superpowers/specs/2026-09-01-local-auth-design.md`

## Global Constraints

- Адаптер и ручки **синхронные** (`def`), не `async def` (кроме уже существующего `ragkb_error_handler`).
- В `backend/ragkb/` нет импортов `sqlalchemy` / `alembic`.
- Слайсовый `service.py` не импортирует другие `ragkb.features.*` (кроме bootstrap).
- `router.py` слайса не импортирует `ragkb.core` и `*.ports`.
- Пароль: Argon2 через `argon2-cffi`. Кука: имя `ragkb_session`, `HttpOnly`, `Path=/`, `SameSite=Lax`, срок 7 суток, `Secure` если HTTPS или `X-Forwarded-Proto: https`.
- Логин канонически: `strip().lower()`; 3–32 символа, только `[a-z0-9._-]`. Пароль 8–128 символов.
- Занятый логин — 409. Неверный вход — 401 с одним `detail` для «нет пользователя» и «плохой пароль».
- `GET /health`, `POST /auth/register`, `POST /auth/login` без сессии. Остальное в `session` — с кукой.
- `GET /auth/me` в `disabled` — 200 `{"username": "anonymous"}`; в `proxy` — из заголовков или 401; иначе фронт с `make backend` уйдёт в цикл на `/login`.
- Язык комментариев и пользовательских `detail` — русский.
- Коммит после каждой задачи. Не пушить, пока не попросят.
- Исторические планы в `docs/superpowers/plans/` не переписывать.

## File map

**Создать**

- `backend/migrations/versions/0004_users_sessions.py` — таблицы `users`, `sessions`
- `backend/ragkb/features/auth/__init__.py`
- `backend/ragkb/features/auth/ports.py` — `AccountStore` Protocol
- `backend/ragkb/features/auth/passwords.py` — hash/verify
- `backend/ragkb/features/auth/sqlite.py` — адаптер
- `backend/ragkb/features/auth/schemas.py`
- `backend/ragkb/features/auth/service.py`
- `backend/ragkb/features/auth/router.py`
- `backend/tests/test_session_auth.py`
- `frontend/src/hooks.server.js`
- `frontend/src/routes/login/+page.svelte`
- `frontend/src/routes/register/+page.svelte`
- `frontend/src/routes/api/auth/register/+server.js`
- `frontend/src/routes/api/auth/login/+server.js`
- `frontend/src/routes/api/auth/logout/+server.js`
- `frontend/src/routes/api/auth/me/+server.js`

**Менять**

- `backend/migrations/env.py` — `USER_VERSION_TO_REVISION`; мигрировать `history.path` даже при `history.enabled: false`
- `backend/ragkb/features/chat_conversations/sqlite.py` — `EXPECTED_REVISION = "0004_users_sessions"`
- `backend/ragkb/platform/errors.py` — `Conflict` → 409
- `backend/ragkb/platform/auth.py` — ветка `session`
- `backend/ragkb/platform/app.py` — роутер auth
- `backend/ragkb/platform/container.py` — `accounts: AccountStore`
- `backend/ragkb/platform/deps.py` — `auth_service`
- `backend/ragkb/core/config.py` — комментарий `auth.mode: session`
- `backend/pyproject.toml` — `argon2-cffi`; затем `uv lock`
- `docker-compose.yml` — `RAGKB_AUTH_MODE` по умолчанию `session`
- `.env.example`, `README.md`, `AGENTS.md`, `frontend/README.md`
- `frontend/src/lib/server/backend.js` — `Cookie` + прокси с `Set-Cookie`
- `frontend/src/routes/+layout.svelte` — имя, выход, без оболочки чата на login/register
- `frontend/src/lib/chat.svelte.js`, `frontend/src/lib/events.svelte.js` — `credentials: 'include'`

---

### Task 1: Миграция users/sessions

**Files:**
- Create: `backend/migrations/versions/0004_users_sessions.py`
- Modify: `backend/migrations/env.py`
- Modify: `backend/ragkb/features/chat_conversations/sqlite.py` (только `EXPECTED_REVISION`)
- Test: `backend/tests/test_architecture.py` (уже есть `test_expected_revision_matches_alembic_head`)
- Test: добавить в `backend/tests/test_session_auth.py` один тест схемы (файл создать здесь)

**Interfaces:**
- Consumes: Alembic head был `0003_message_model`
- Produces: ревизия id `0004_users_sessions`; таблицы `users`, `sessions`; `EXPECTED_REVISION == "0004_users_sessions"`; `env.py` всегда открывает файл по `RAGKB_HISTORY_PATH` / `history.path`, **не** возвращает `None` из‑за `history.enabled is False`

- [ ] **Step 1: Write the failing test**

Создать `backend/tests/test_session_auth.py`:

```python
from __future__ import annotations

import sqlite3
from pathlib import Path

from helpers import migrate


def test_migrate_creates_users_and_sessions(tmp_path: Path) -> None:
    db = tmp_path / "h.sqlite3"
    migrate(db)
    conn = sqlite3.connect(str(db))
    names = {
        r[0]
        for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
    }
    assert "users" in names
    assert "sessions" in names
    rev = conn.execute("SELECT version_num FROM alembic_version").fetchone()[0]
    assert rev == "0004_users_sessions"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/test_session_auth.py::test_migrate_creates_users_and_sessions tests/test_architecture.py::test_expected_revision_matches_alembic_head -q`

Expected: FAIL (нет ревизии / нет таблиц)

- [ ] **Step 3: Write minimal implementation**

`backend/migrations/versions/0004_users_sessions.py`:

```python
from alembic import op

revision = "0004_users_sessions"
down_revision = "0003_message_model"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE users (
            id TEXT PRIMARY KEY,
            username TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """
    )
    op.execute(
        """
        CREATE TABLE sessions (
            token_hash TEXT PRIMARY KEY,
            user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            expires_at TEXT NOT NULL
        )
        """
    )
    op.execute("PRAGMA user_version = 4")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS sessions")
    op.execute("DROP TABLE IF EXISTS users")
    op.execute("PRAGMA user_version = 3")
```

В `env.py` добавить `4: "0004_users_sessions"` в `USER_VERSION_TO_REVISION`.

Заменить `_db_path` так, чтобы при отсутствии `x.db_path` и `RAGKB_HISTORY_PATH` брался `Config.load(...).history.path` **всегда**, без `if not cfg.history.enabled: return None`.

В `sqlite.py` истории: `EXPECTED_REVISION = "0004_users_sessions"`.

- [ ] **Step 4: Run the tests and make sure they pass**

Run: `cd backend && uv run pytest tests/test_session_auth.py::test_migrate_creates_users_and_sessions tests/test_architecture.py -q`

Expected: PASS (архитектурные тесты тоже зелёные)

- [ ] **Step 5: Commit**

```bash
git add backend/migrations/versions/0004_users_sessions.py \
  backend/migrations/env.py \
  backend/ragkb/features/chat_conversations/sqlite.py \
  backend/tests/test_session_auth.py
git commit -m "$(cat <<'EOF'
Добавить таблицы users и sessions в схему истории.

Ревизия 0004; миграции идут в файл SQLite даже если история диалогов выключена.
EOF
)"
```

---

### Task 2: Хеш пароля и sqlite-адаптер

**Files:**
- Create: `backend/ragkb/features/auth/__init__.py` (пустое или docstring)
- Create: `backend/ragkb/features/auth/ports.py`
- Create: `backend/ragkb/features/auth/passwords.py`
- Create: `backend/ragkb/features/auth/sqlite.py`
- Modify: `backend/pyproject.toml` (зависимость)
- Modify: `backend/tests/test_session_auth.py`
- Run: `cd backend && uv lock` после правки зависимостей

**Interfaces:**
- Consumes: файл БД после `migrate()`
- Produces:
  - `hash_password(plain: str) -> str`
  - `verify_password(plain: str, password_hash: str) -> bool`
  - `COOKIE_NAME = "ragkb_session"`
  - `SESSION_DAYS = 7`
  - `class SqliteAccounts:`
    - `__init__(self, path: str | Path) -> None`
    - `create_user(self, username: str, password_hash: str) -> str`  # user id; IntegrityError наружу не пускать — пусть сервис ловит `sqlite3.IntegrityError` **или** адаптер поднимает свой `UsernameTaken` в `ragkb.features.auth.sqlite` (не RagkbError). Предпочтение: адаптер бросает `sqlite3.IntegrityError`, сервис в задаче 3 мапит в `Conflict`.
    - `get_by_username(self, username: str) -> tuple[str, str, str] | None`  # `(id, username, password_hash)`
    - `create_session(self, user_id: str, token_hash: str, expires_at: str) -> None`
    - `delete_session(self, token_hash: str) -> None`
    - `user_for_token_hash(self, token_hash: str) -> tuple[str, str] | None`  # `(id, username)` если сессия жива (`expires_at` >= сейчас UTC isoformat). Истёкшая — как None, строку можно не удалять.

`connect` скопировать по образцу `chat_conversations/sqlite.py` (mkdir, `0o600`, WAL, FK). Проверку ревизии импортировать: `from ragkb.features.chat_conversations.sqlite import EXPECTED_REVISION` и тот же запрос к `alembic_version` (допустимо: это не `service.py`).

- [ ] **Step 1: Write the failing tests**

Добавить в `test_session_auth.py`:

```python
from ragkb.features.auth.passwords import hash_password, verify_password
from ragkb.features.auth.sqlite import SqliteAccounts


def test_password_roundtrip() -> None:
    hashed = hash_password("correct-horse")
    assert hashed != "correct-horse"
    assert verify_password("correct-horse", hashed)
    assert not verify_password("wrong", hashed)


def test_accounts_user_and_session(tmp_path: Path) -> None:
    db = tmp_path / "h.sqlite3"
    migrate(db)
    store = SqliteAccounts(db)
    uid = store.create_user("ada", hash_password("password1"))
    row = store.get_by_username("ada")
    assert row is not None
    assert row[0] == uid
    store.create_session(uid, "hash1", "2099-01-01T00:00:00+00:00")
    assert store.user_for_token_hash("hash1") == (uid, "ada")
    store.create_session(uid, "old", "2000-01-01T00:00:00+00:00")
    assert store.user_for_token_hash("old") is None
    store.delete_session("hash1")
    assert store.user_for_token_hash("hash1") is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/test_session_auth.py::test_password_roundtrip tests/test_session_auth.py::test_accounts_user_and_session -q`

Expected: FAIL import / not defined

- [ ] **Step 3: Write minimal implementation**

В `pyproject.toml` в `dependencies` добавить `"argon2-cffi>=23.1"`.

`passwords.py`: `PasswordHasher()` из `argon2`; `verify_password` ловит `VerifyMismatchError` и `InvalidHashError` → `False`.

`ports.py`:

```python
from typing import Protocol

class AccountStore(Protocol):
    def create_user(self, username: str, password_hash: str) -> str: ...
    def get_by_username(self, username: str) -> tuple[str, str, str] | None: ...
    def create_session(self, user_id: str, token_hash: str, expires_at: str) -> None: ...
    def delete_session(self, token_hash: str) -> None: ...
    def user_for_token_hash(self, token_hash: str) -> tuple[str, str] | None: ...
```

`sqlite.py`: UUID для `id`; `created_at` через тот же UTC isoformat, что история.

Затем `cd backend && uv lock && uv sync --extra migrations --extra dev`.

- [ ] **Step 4: Run the tests and make sure they pass**

Run: `cd backend && uv run pytest tests/test_session_auth.py -q`

Expected: PASS (включая тест миграции)

- [ ] **Step 5: Commit**

```bash
git add backend/pyproject.toml backend/uv.lock \
  backend/ragkb/features/auth \
  backend/tests/test_session_auth.py
git commit -m "$(cat <<'EOF'
Добавить хранилище аккаунтов: Argon2 и sqlite3.

Пароли и сессии пишутся в тот же файл, что история диалогов.
EOF
)"
```

---

### Task 3: Сервис, HTTP, current_user

**Files:**
- Create: `backend/ragkb/features/auth/schemas.py`
- Create: `backend/ragkb/features/auth/service.py`
- Create: `backend/ragkb/features/auth/router.py`
- Modify: `backend/ragkb/platform/errors.py`
- Modify: `backend/ragkb/platform/auth.py`
- Modify: `backend/ragkb/platform/container.py`
- Modify: `backend/ragkb/platform/deps.py`
- Modify: `backend/ragkb/platform/app.py`
- Modify: `backend/ragkb/core/config.py` (комментарий у `AuthConfig.mode`)
- Modify: `backend/tests/test_session_auth.py`

**Interfaces:**
- Consumes: `SqliteAccounts`, `hash_password`, `verify_password`
- Produces:
  - `class Conflict(RagkbError)` в `errors.py`; `_STATUS[Conflict] = 409`
  - `class Credentials(BaseModel): username: str; password: str` с валидаторами длины и логина (нормализация username внутри валидатора → каноническая строка). Невалидное тело — 422.
  - `class AuthService:`
    - `__init__(self, store: AccountStore) -> None`
    - `register(self, username: str, password: str) -> tuple[str, str]`  # `(username, raw_cookie_token)`
    - `login(self, username: str, password: str) -> tuple[str, str]`
    - `logout(self, raw_token: str | None) -> None`
    - `me(self, raw_token: str | None) -> str`  # username; иначе `Unauthenticated`
  - Сессия: `secrets.token_urlsafe(32)`; в БД `hashlib.sha256(raw.encode()).hexdigest()`; `expires_at` = now+7d UTC isoformat.
  - Повторный login/register при живой куке: `logout` старого токена, затем новая сессия.
  - Ручки: `POST /auth/register`, `POST /auth/login` ставят куку через `Response`; `POST /auth/logout` 204 `delete_cookie`; `GET /auth/me`.
  - `def set_session_cookie(response: Response, request: Request, token: str) -> None` в router (не в core): `secure` если `request.url.scheme == "https"` или `request.headers.get("x-forwarded-proto", "").split(",")[0].strip() == "https"`.
  - `current_user`: `disabled` → anonymous; `session` → `container.accounts.user_for_token_hash(sha256(cookie))` иначе `Unauthenticated("Не аутентифицирован")`; `proxy` — как сейчас заголовки.
  - `Container`: всегда `self.accounts = SqliteAccounts(cfg.history.path)` (нужен файл; тесты уже делают `migrate` в фикстуре `cfg`).
  - `create_app`: `app.include_router(auth_router)` **до** остальных, не принципиально по порядку.
  - `GET /auth/me` в режиме не session: если `disabled` — `{"username": "anonymous"}` без куки; если `proxy` — `current_user` и вернуть его `name`.

Текст 401 на логин: `"Неверный логин или пароль"`.  
409: `"Такой логин уже занят"`.

- [ ] **Step 1: Write the failing tests**

Добавить в `test_session_auth.py` клиентские тесты (фикстура `cfg` из conftest + `migrate` уже есть). Не использовать общий `client` (он `auth.mode=disabled`).

```python
from fastapi.testclient import TestClient

from ragkb.platform.app import create_app


def _session_client(cfg):
    cfg.auth.mode = "session"
    return TestClient(create_app(cfg))


def test_register_login_me_logout_bootstrap(indexed):
    client = _session_client(indexed)
    r = client.post(
        "/auth/register",
        json={"username": "Ada", "password": "password1"},
    )
    assert r.status_code == 200
    assert r.json() == {"username": "ada"}
    assert r.cookies.get("ragkb_session")
    assert client.get("/auth/me").json() == {"username": "ada"}
    boot = client.get(
        "/bootstrap",
        params={"session_id": "00000000-0000-4000-8000-000000000002"},
    )
    assert boot.status_code == 200
    assert boot.json()["user"]["name"] == "ada"
    client.post("/auth/logout")
    assert client.get("/auth/me").status_code == 401
    assert client.get("/health").status_code == 200


def test_duplicate_username(indexed):
    client = _session_client(indexed)
    body = {"username": "bob", "password": "password1"}
    assert client.post("/auth/register", json=body).status_code == 200
    client.post("/auth/logout")
    assert client.post("/auth/register", json=body).status_code == 409


def test_bad_login_same_message(indexed):
    client = _session_client(indexed)
    a = client.post("/auth/login", json={"username": "nobody", "password": "password1"})
    client.post("/auth/register", json={"username": "eve", "password": "password1"})
    client.post("/auth/logout")
    b = client.post("/auth/login", json={"username": "eve", "password": "wrongpass"})
    assert a.status_code == b.status_code == 401
    assert a.json()["detail"] == b.json()["detail"]


def test_short_password_rejected(indexed):
    client = _session_client(indexed)
    r = client.post("/auth/register", json={"username": "sam", "password": "short"})
    assert r.status_code == 422


def test_bootstrap_unauthorized_without_cookie(indexed):
    client = _session_client(indexed)
    r = client.get(
        "/bootstrap",
        params={"session_id": "00000000-0000-4000-8000-000000000002"},
    )
    assert r.status_code == 401


def test_me_disabled_is_anonymous(indexed):
    indexed.auth.mode = "disabled"
    client = TestClient(create_app(indexed))
    assert client.get("/auth/me").json() == {"username": "anonymous"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/test_session_auth.py -q`

Expected: FAIL (нет ручек / 401 на bootstrap иначе)

- [ ] **Step 3: Write minimal implementation**

Схемы pydantic: `username` Field min 3 max 32; после lower+strip regex `^[a-z0-9._-]+$`. `password` min 8 max 128.

Router: читать куку `request.cookies.get("ragkb_session")`. Register/login: если кука была — `svc.logout(old)`.

`delete_cookie("ragkb_session", path="/")`.

Не ставить `docs_url`. Не логировать пароль.

- [ ] **Step 4: Run the tests and make sure they pass**

Run: `cd backend && uv run pytest -q`

Expected: PASS весь набор, включая старый `tests/test_auth.py` (proxy/disabled)

- [ ] **Step 5: Commit**

```bash
git add backend/ragkb/features/auth backend/ragkb/platform \
  backend/ragkb/core/config.py backend/tests/test_session_auth.py
git commit -m "$(cat <<'EOF'
Включить регистрацию, вход и сессионную куку в FastAPI.

Режим auth.mode=session читает личность только из куки, не из заголовков.
EOF
)"
```

---

### Task 4: BFF проксирует куку

**Files:**
- Modify: `frontend/src/lib/server/backend.js`
- Create: четыре `+server.js` под `frontend/src/routes/api/auth/{register,login,logout,me}/`

**Interfaces:**
- Consumes: бэкенд `/auth/*`
- Produces: `backend()` копирует входящий заголовок `cookie` на FastAPI. Новая функция `proxyAuth(path, request, init)` возвращает `Response` с телом JSON (или пустым для 204) **и всеми** `set-cookie` с апстрима (`upstream.headers.getSetCookie()`). Не использовать `proxyJson` для login/register/logout: он теряет `Set-Cookie`.
- `RAGKB_DEV_USER` по-прежнему можно подставлять, если cookie нет (локальный `proxy`). На `session` бэкенд заголовок игнорирует.

- [ ] **Step 1: Write the failing check (контракт вручную в коде BFF)**

Нет фронтовых pytest. Критерий: `proxyAuth` и проброс cookie в `backend()`. Добавить `proxyAuth` так:

```javascript
/**
 * @param {string} path
 * @param {Request} request
 * @param {RequestInit} [init]
 */
export async function proxyAuth(path, request, init = {}) {
	let upstream;
	try {
		upstream = await backend(path, request, init);
	} catch (error) {
		return json({ detail: unreachable(error) }, { status: 502 });
	}
	const headers = new Headers();
	headers.set('content-type', upstream.headers.get('content-type') || 'application/json');
	for (const cookie of upstream.headers.getSetCookie?.() ?? []) {
		headers.append('set-cookie', cookie);
	}
	if (upstream.status === 204) {
		return new Response(null, { status: 204, headers });
	}
	const body = await upstream.arrayBuffer();
	return new Response(body, { status: upstream.status, headers });
}
```

В `identity` / `backend`:

```javascript
	const cookie = request.headers.get('cookie');
	if (cookie) headers.cookie = cookie;
```

`register/+server.js`:

```javascript
import { proxyAuth } from '$lib/server/backend.js';

export async function POST({ request }) {
	return proxyAuth('/auth/register', request, { method: 'POST', body: await request.text() });
}
```

Аналогично `login`. `logout`: `POST`, body не нужен. `me`: `GET` без body.

- [ ] **Step 2: Run svelte-check**

Run: `cd frontend && bun run check`

Expected: PASS (или поправить типы JSDoc)

- [ ] **Step 3: Commit**

```bash
git add frontend/src/lib/server/backend.js frontend/src/routes/api/auth
git commit -m "$(cat <<'EOF'
Пробросить сессионную куку через BFF.

Login/register отдают Set-Cookie с апстрима, остальные запросы несут Cookie.
EOF
)"
```

---

### Task 5: Страницы входа и редирект

**Files:**
- Create: `frontend/src/hooks.server.js`
- Create: `frontend/src/routes/login/+page.svelte`
- Create: `frontend/src/routes/register/+page.svelte`
- Modify: `frontend/src/routes/+layout.svelte`
- Modify: `frontend/src/lib/chat.svelte.js` — все `fetch('/api/...` с `credentials: 'include'`
- Modify: `frontend/src/lib/events.svelte.js` — то же

**Interfaces:**
- Consumes: `/api/auth/me`, `/api/auth/login`, `/api/auth/register`, `/api/auth/logout`
- Produces: без сессии HTML кроме `/login` и `/register` → 303 `/login`. `/login` и `/register` при 200 от me → `/new`. `/api/*` и `/health` хук не редиректит. `start()` не вызывать на login/register. Шапка чата: username и кнопка «Выйти».

- [ ] **Step 1: Implement hooks**

`hooks.server.js`:

```javascript
import { redirect } from '@sveltejs/kit';
import { backend } from '$lib/server/backend.js';

const PUBLIC = new Set(['/login', '/register']);

export async function handle({ event, resolve }) {
	const path = event.url.pathname;
	if (path.startsWith('/api/') || path === '/health') {
		return resolve(event);
	}
	let me = 401;
	try {
		const res = await backend('/auth/me', event.request);
		me = res.status;
	} catch {
		me = 502;
	}
	if (PUBLIC.has(path)) {
		if (me === 200) redirect(303, '/new');
		return resolve(event);
	}
	if (me !== 200) redirect(303, '/login');
	return resolve(event);
}
```

В режиме `disabled` `/auth/me` всегда 200 — редиректа на login не будет (локальный `make backend`).

Формы: `username`, `password`, POST `/api/auth/login` или `/register` с `credentials: 'include'`, `content-type: application/json`. Успех → `goto('/new')`. Ошибка — `detail` на странице. Ссылка на соседнюю форму.

В `+layout.svelte`: если `$page.url.pathname` это `/login` или `/register` — только `{@render children()}`, без aside/шапки чата и без `start()` в onMount.

Иначе в header после модели:

```svelte
{#if chat.user?.name}
  <span>{chat.user.name}</span>
  <button type="button" onclick={logout}>Выйти</button>
{/if}
```

`logout`: `fetch('/api/auth/logout', { method: 'POST', credentials: 'include' })` затем `location.href = '/login'`.

Каждый существующий `fetch` к `/api/` в `chat.svelte.js` и `events.svelte.js` дополнить `credentials: 'include'`.

- [ ] **Step 2: Run check**

Run: `cd frontend && bun run check`

Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add frontend/src/hooks.server.js \
  frontend/src/routes/login frontend/src/routes/register \
  frontend/src/routes/+layout.svelte \
  frontend/src/lib/chat.svelte.js frontend/src/lib/events.svelte.js
git commit -m "$(cat <<'EOF'
Добавить страницы входа и регистрации.

Без сессии хук отправляет на /login; кука ходит во все запросы к BFF.
EOF
)"
```

---

### Task 6: Compose, конфиг, документация

**Files:**
- Modify: `docker-compose.yml` — `RAGKB_AUTH_MODE: ${RAGKB_AUTH_MODE:-session}`
- Modify: `.env.example` — `RAGKB_AUTH_MODE=session`, пояснение что Keycloak/Angie OIDC для ragkb больше не источник личности
- Modify: `backend/config.yaml` — можно не менять default `proxy` в dataclass (отказ по умолчанию для голого uvicorn без compose). Compose задаёт session.
- Modify: `README.md`, `AGENTS.md`, `frontend/README.md` — вход формами; Angie на сервере не должен требовать OIDC на `/login`, `/register`, `/api/auth`; `RAGKB_DEV_USER` не заменяет сессию при `session`
- Modify: `Makefile` — цель `backend` оставить `RAGKB_AUTH_MODE=disabled`; в `help` одна строка про это

**Interfaces:**
- Consumes: Task 3–5
- Produces: выкладка `make up` требует регистрации в UI

- [ ] **Step 1: Правки файлов** как в Files

- [ ] **Step 2: Run backend tests again**

Run: `cd backend && uv run pytest -q`

Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add docker-compose.yml .env.example README.md AGENTS.md \
  frontend/README.md Makefile backend/config.yaml
git commit -m "$(cat <<'EOF'
Перевести compose на auth.mode=session и описать вход формами.

На сервере Angie не должен закрывать /login корпоративным SSO.
EOF
)"
```

Если `config.yaml` не менялся — не включать его в `git add`.

---

## Spec coverage

| Спека | Задача |
|---|---|
| слайс auth, register/login/logout/me | 3 |
| SQLite + Alembic 0004, sqlite3, sync | 1–2 |
| Argon2, правила логина/пароля, 409/401 | 2–3 |
| кука 7 дней, Secure/Lax/HttpOnly | 3 |
| current_user session не из заголовков | 3 |
| BFF /api/auth и Cookie | 4 |
| /login /register, редирект, имя, Выйти | 5 |
| README/AGENTS/env/compose | 6 |
| тесты + architecture sqlalchemy | 1–3 |
| SSO, админка, JWT — вне работы | нет задач |

`GET /auth/me` в `disabled` — уточнение плана, чтобы `make backend` + фронт не ломались; в спеке режима `session` это не противоречит.

## Placeholder scan

Нет TBD. Имена: `SqliteAccounts`, `AuthService`, `COOKIE_NAME`, `Conflict`, `proxyAuth`, ревизия `0004_users_sessions`.
