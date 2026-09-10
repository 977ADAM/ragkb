# Admin-created accounts Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Публичный signup всегда 403; людей заводит админ на `/admin/users` (имя, пароль, роль).

**Architecture:** `POST /auths/signup` бросает `Forbidden` без разбора тела и без записи в БД. Создание — `AdminUsersService.create` (Argon2 + `AccountStore.create_user`, без сессии) через `POST /admin/users`. UI: форма над таблицей; `/register` без полей.

**Tech Stack:** FastAPI, Pydantic, Argon2, SvelteKit BFF.

**Спека:** `docs/superpowers/specs/2026-09-10-admin-create-users-design.md`

## Global Constraints

- `POST /api/v1/auths/signup` всегда 403 `{"detail": "регистрация закрыта, учётку создаёт администратор"}`; тело не разбирать; куку не ставить.
- Ручка signup остаётся публичной (без `current_user`), иначе будет 401 вместо 403.
- `POST /api/v1/admin/users` — сессия + `require_admin`; 201 `{username, role, created_at}`.
- Логин: lower+trim, 3–32, `[a-z0-9._-]`. Пароль: 8–128. `role` только `user` или `admin`.
- Занятый логин — 409 (`Conflict` из `create_user`). Невалидное тело — 422. Не-админ — 403.
- Новому пользователю сессию не открывать; сессию админа не гасить.
- `ensure-admin` не трогать. Исторические планы в `docs/superpowers/plans/` не переписывать.
- Не трогать `GET /users`, сброс чужого пароля, письма.
- SQLAlchemy не импортировать в `core/` кроме `database.py`.
- Коммит после каждой задачи. Не пушить, пока не попросят.
- Тесты sqlite: `cd backend && uv run pytest …` (без Postgres). `tests/test_session_auth.py` нужен `RAGKB_TEST_DATABASE_URL`.

## File map

**Создать**

- ничего: схема `CreateUser` в существующем `api/schemas/auth.py`

**Менять**

- `backend/ragkb/api/schemas/auth.py` — `CreateUser`
- `backend/ragkb/services/admin_users.py` — `create`
- `backend/ragkb/api/routes/admin.py` — `POST /users`
- `backend/ragkb/api/routes/auths.py` — signup → 403; убрать вызов `register`
- `backend/ragkb/services/auth.py` — удалить `AuthService.register`, если больше никто не зовёт
- `backend/tests/test_admin_http.py` — создание user/admin, 403, 409, 422, сессия жива
- `backend/tests/test_guard.py` — signup 403 на sqlite
- `backend/tests/test_session_auth.py` — заводить людей через `create_user` + `signin`, не signup
- `frontend/src/lib/server/backend.js` — `proxyJson` пробрасывает `upstream.status` (иначе 201 станет 200)
- `frontend/src/routes/api/admin/users/+server.js` — `POST`
- `frontend/src/routes/admin/users/+page.svelte` — форма
- `frontend/src/routes/register/+page.svelte` — без формы
- `README.md`, `AGENTS.md`, `frontend/README.md`, `docs/OpenAPI 3.0.0 Спецификация — Auth API для RAG-системы.yml`
- `docs/superpowers/specs/2026-09-10-admin-create-users-design.md` — статус «готово» в последней задаче

---

### Task 1: `AdminUsersService.create` и `POST /admin/users`

**Files:**
- Modify: `backend/ragkb/api/schemas/auth.py`
- Modify: `backend/ragkb/services/admin_users.py`
- Modify: `backend/ragkb/api/routes/admin.py`
- Test: `backend/tests/test_admin_http.py`

**Interfaces:**
- Consumes: `AccountStore.create_user(username, password_hash, role) -> str`; `AccountStore.get_profile(username) -> tuple[str, datetime] | None`; `hash_password(plain: str) -> str`; `Conflict` при занятом логине
- Produces: `AdminUsersService.create(username: str, password: str, role: str) -> dict[str, str]` с ключами `username`, `role`, `created_at` (ISO); HTTP `POST /api/v1/admin/users` статус 201

- [ ] **Step 1: Write the failing tests**

В конец `backend/tests/test_admin_http.py` (фикстура `sqlite_url` уже сеет `ada`/admin и `bob`/user, пароль `password1`):

```python
def test_admin_creates_user(tmp_path: Path, sqlite_url: str) -> None:
    with _admin_client(_session_cfg(tmp_path, sqlite_url)) as client:
        _signin(client, "ada")
        res = client.post(
            "/api/v1/admin/users",
            json={"username": "Eve", "password": "password1", "role": "user"},
        )
        assert res.status_code == 201
        body = res.json()
        assert body["username"] == "eve"
        assert body["role"] == "user"
        assert body["created_at"]
        users = {(u["username"], u["role"]) for u in client.get("/api/v1/admin/users").json()["users"]}
        assert ("eve", "user") in users
        assert client.get("/api/v1/auths/me").json() == {"username": "ada", "role": "admin"}


def test_admin_creates_admin(tmp_path: Path, sqlite_url: str) -> None:
    with _admin_client(_session_cfg(tmp_path, sqlite_url)) as client:
        _signin(client, "ada")
        res = client.post(
            "/api/v1/admin/users",
            json={"username": "root", "password": "password1", "role": "admin"},
        )
        assert res.status_code == 201
        assert res.json()["role"] == "admin"


def test_plain_user_cannot_create(tmp_path: Path, sqlite_url: str) -> None:
    with _admin_client(_session_cfg(tmp_path, sqlite_url)) as client:
        _signin(client, "bob")
        res = client.post(
            "/api/v1/admin/users",
            json={"username": "eve", "password": "password1", "role": "user"},
        )
        assert res.status_code == 403


def test_create_duplicate_username_is_409(tmp_path: Path, sqlite_url: str) -> None:
    with _admin_client(_session_cfg(tmp_path, sqlite_url)) as client:
        _signin(client, "ada")
        res = client.post(
            "/api/v1/admin/users",
            json={"username": "bob", "password": "password1", "role": "user"},
        )
        assert res.status_code == 409
        assert res.json()["detail"] == "Такой логин уже занят"


def test_create_rejects_short_password_and_bad_role(
    tmp_path: Path, sqlite_url: str
) -> None:
    with _admin_client(_session_cfg(tmp_path, sqlite_url)) as client:
        _signin(client, "ada")
        short = client.post(
            "/api/v1/admin/users",
            json={"username": "sam", "password": "short", "role": "user"},
        )
        assert short.status_code == 422
        bad_role = client.post(
            "/api/v1/admin/users",
            json={"username": "sam", "password": "password1", "role": "owner"},
        )
        assert bad_role.status_code == 422
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && uv run pytest tests/test_admin_http.py::test_admin_creates_user tests/test_admin_http.py::test_admin_creates_admin tests/test_admin_http.py::test_plain_user_cannot_create tests/test_admin_http.py::test_create_duplicate_username_is_409 tests/test_admin_http.py::test_create_rejects_short_password_and_bad_role -q --tb=line`

Expected: FAIL (метод не разрешён / 404 / нет `create`)

- [ ] **Step 3: Schema, service, route**

`backend/ragkb/api/schemas/auth.py` — добавить импорт и класс:

```python
from typing import Literal
```

после `Credentials`:

```python
class CreateUser(Credentials):
    role: Literal["user", "admin"]
```

`backend/ragkb/services/admin_users.py` — импорт и метод:

```python
from ragkb.services.auth import hash_password
```

в класс `AdminUsersService` после `list`:

```python
    async def create(self, username: str, password: str, role: str) -> dict[str, str]:
        if role not in _ROLES:
            raise InvalidRequest("роль только user или admin")
        await self._store.create_user(username, hash_password(password), role=role)
        profile = await self._store.get_profile(username)
        if profile is None:
            raise NotFound("Пользователь не найден")
        new_role, created_at = profile
        return _user_payload(username, new_role, created_at)
```

`backend/ragkb/api/routes/admin.py`:

```python
from ragkb.api.schemas.auth import CreateUser
```

после `list_users`:

```python
@router.post("/users", status_code=201)
async def create_user(
    body: CreateUser,
    svc: AdminUsers,
    actor: User = Depends(require_admin),
) -> dict[str, str]:
    result = await svc.create(body.username, body.password, body.role)
    log.info(
        "админ %s: создан пользователь %s роль %s",
        actor.name,
        result["username"],
        result["role"],
    )
    return result
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && uv run pytest tests/test_admin_http.py -q --tb=short`

Expected: PASS (включая старые тесты списка/роли/удаления)

- [ ] **Step 5: Commit**

```bash
git add backend/ragkb/api/schemas/auth.py \
  backend/ragkb/services/admin_users.py \
  backend/ragkb/api/routes/admin.py \
  backend/tests/test_admin_http.py
git commit -m "$(cat <<'EOF'
Let admins create users with username, password, and role.

EOF
)"
```

---

### Task 2: Закрыть signup и перевести тесты на `create_user`

**Files:**
- Modify: `backend/ragkb/api/routes/auths.py`
- Modify: `backend/ragkb/services/auth.py` — удалить `register`, если на него нет ссылок
- Modify: `backend/tests/test_guard.py`
- Modify: `backend/tests/test_session_auth.py`

**Interfaces:**
- Consumes: `Forbidden` из `ragkb.core.errors` (уже мапится на 403 в `api/errors.py`)
- Produces: `POST /api/v1/auths/signup` → 403, без `Set-Cookie`, без строки в `users`

- [ ] **Step 1: Write the failing sqlite test and flip the guard test**

В `backend/tests/test_guard.py` заменить `test_session_auth_on_sqlite` на два теста:

```python
def test_signup_is_closed_on_sqlite(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from alembic import command
    from alembic.config import Config as AlembicConfig
    from fastapi.testclient import TestClient
    from sqlalchemy import create_engine, text

    from ragkb.core.database import alembic_sync_url

    db = tmp_path / "ragkb.sqlite3"
    url = f"sqlite+aiosqlite:///{db}"
    cfg_alembic = AlembicConfig(str(BACKEND_ROOT / "alembic.ini"))
    cfg_alembic.set_main_option("script_location", str(BACKEND_ROOT / "migrations"))
    monkeypatch.setenv("RAGKB_DATABASE_URL", url)
    command.upgrade(cfg_alembic, "head")
    cfg = Settings()
    cfg.database_url = url
    cfg.auth.mode = "session"
    cfg.history.enabled = True
    cfg.store.backend = "numpy"
    cfg.index_dir = str(tmp_path / "idx")
    with TestClient(make_app(cfg)) as client:
        r = client.post(
            "/api/v1/auths/signup",
            json={"username": "ada", "password": "password1"},
        )
        assert r.status_code == 403
        assert r.json()["detail"] == "регистрация закрыта, учётку создаёт администратор"
        assert r.cookies.get("ragkb_session") is None
        assert client.get("/api/v1/auths/me").status_code == 401
    engine = create_engine(alembic_sync_url(url))
    with engine.connect() as conn:
        n = conn.execute(text("SELECT COUNT(*) FROM users")).scalar()
    engine.dispose()
    assert n == 0


def test_session_auth_on_sqlite(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import asyncio

    from alembic import command
    from alembic.config import Config as AlembicConfig
    from fastapi.testclient import TestClient

    from ragkb.core.database import make_engine, make_session_factory
    from ragkb.db.repos.auth import PostgresAccounts
    from ragkb.services.auth import hash_password

    db = tmp_path / "ragkb.sqlite3"
    url = f"sqlite+aiosqlite:///{db}"
    cfg_alembic = AlembicConfig(str(BACKEND_ROOT / "alembic.ini"))
    cfg_alembic.set_main_option("script_location", str(BACKEND_ROOT / "migrations"))
    monkeypatch.setenv("RAGKB_DATABASE_URL", url)
    command.upgrade(cfg_alembic, "head")

    async def _seed() -> None:
        engine = make_engine(url)
        store = PostgresAccounts(make_session_factory(engine))
        await store.create_user("ada", hash_password("password1"), role="user")
        await engine.dispose()

    asyncio.run(_seed())
    cfg = Settings()
    cfg.database_url = url
    cfg.auth.mode = "session"
    cfg.history.enabled = True
    cfg.store.backend = "numpy"
    cfg.index_dir = str(tmp_path / "idx")
    with TestClient(make_app(cfg)) as client:
        r = client.post(
            "/api/v1/auths/signin",
            json={"username": "ada", "password": "password1"},
        )
        assert r.status_code == 200
        assert client.get("/api/v1/auths/me").json() == {"username": "ada", "role": "user"}
```

- [ ] **Step 2: Run sqlite tests to verify signup still 200 (RED for closed signup)**

Run: `cd backend && uv run pytest tests/test_guard.py::test_signup_is_closed_on_sqlite -q --tb=line`

Expected: FAIL (`assert 200 == 403` или `assert r.json()["detail"] == …`)

- [ ] **Step 3: Close the HTTP handler**

В `backend/ragkb/api/routes/auths.py` заменить `signup` целиком. Импорт `Forbidden` уже есть. Параметр `body` и вызов сервиса убрать:

```python
@router.post("/signup")
async def signup() -> dict[str, str]:
    raise Forbidden("регистрация закрыта, учётку создаёт администратор")
```

Не вызывать `svc.register`. Если `AuthService.register` больше нигде не импортируется (`rg register` по `backend/`), удалить метод `register` из `backend/ragkb/services/auth.py`.

- [ ] **Step 4: Run sqlite tests**

Run: `cd backend && uv run pytest tests/test_guard.py tests/test_admin_http.py -q --tb=short`

Expected: PASS

- [ ] **Step 5: Rewrite `test_session_auth.py` helpers and tests that posted signup**

В `backend/tests/test_session_auth.py` добавить рядом с `_session_client`:

```python
def _seed_user(
    url: str, username: str, password: str = "password1", role: str = "user"
) -> None:
    async def _run() -> None:
        engine = make_engine(url)
        store = PostgresAccounts(make_session_factory(engine))
        await store.create_user(username, hash_password(password), role=role)
        await engine.dispose()

    asyncio.run(_run())
```

Импорты, которых ещё нет: `asyncio`; `PostgresAccounts` из `ragkb.db.repos.auth`; `hash_password` из `ragkb.services.auth`; `make_engine`, `make_session_factory` из `ragkb.core.database`.

Заменить тесты так (signup больше не создаёт людей):

`test_register_login_me_logout_bootstrap` → `test_login_me_logout_bootstrap`:

```python
def test_login_me_logout_bootstrap(indexed):
    _seed_user(database_url(), "ada")
    with _session_client(indexed) as client:
        r = client.post(
            "/api/v1/auths/signin",
            json={"username": "Ada", "password": "password1"},
        )
        assert r.status_code == 200
        assert r.json() == {"username": "ada"}
        assert r.cookies.get("ragkb_session")
        assert client.get("/api/v1/auths/me").json() == {"username": "ada", "role": "user"}
        boot = client.get(
            "/api/v1/bootstrap",
            params={"session_id": "00000000-0000-4000-8000-000000000002"},
        )
        assert boot.status_code == 200
        assert boot.json()["user"]["name"] == "ada"
        assert boot.json()["user"]["is_admin"] is False
        assert boot.json()["capabilities"]["reindex"] is False
        assert client.post("/api/v1/index/rebuild").status_code == 403
        client.post("/api/v1/auths/signout")
        assert client.get("/api/v1/auths/me").status_code == 401
        assert client.get("/health").status_code == 200
```

`test_duplicate_username` — дубль через админский POST (нужен админ):

```python
def test_duplicate_username(indexed):
    _seed_user(database_url(), "ada", role="admin")
    with _session_client(indexed) as client:
        _signin = client.post(
            "/api/v1/auths/signin",
            json={"username": "ada", "password": "password1"},
        )
        assert _signin.status_code == 200
        body = {"username": "bob", "password": "password1", "role": "user"}
        assert client.post("/api/v1/admin/users", json=body).status_code == 201
        assert client.post("/api/v1/admin/users", json=body).status_code == 409
```

`test_bad_login_same_message`:

```python
def test_bad_login_same_message(indexed):
    _seed_user(database_url(), "eve")
    with _session_client(indexed) as client:
        a = client.post(
            "/api/v1/auths/signin", json={"username": "nobody", "password": "password1"}
        )
        b = client.post(
            "/api/v1/auths/signin", json={"username": "eve", "password": "wrongpass"}
        )
        assert a.status_code == b.status_code == 401
        assert a.json()["detail"] == b.json()["detail"]
```

`test_failed_login_keeps_existing_session`:

```python
def test_failed_login_keeps_existing_session(indexed):
    _seed_user(database_url(), "ada")
    with _session_client(indexed) as client:
        assert (
            client.post(
                "/api/v1/auths/signin",
                json={"username": "ada", "password": "password1"},
            ).status_code
            == 200
        )
        unknown = client.post(
            "/api/v1/auths/signin",
            json={"username": "nobody", "password": "password1"},
        )
        assert unknown.status_code == 401
        assert client.get("/api/v1/auths/me").status_code == 200
        assert client.get("/api/v1/auths/me").json() == {"username": "ada", "role": "user"}
        wrong = client.post(
            "/api/v1/auths/signin",
            json={"username": "bob", "password": "wrongpass"},
        )
        assert wrong.status_code == 401
        assert client.get("/api/v1/auths/me").json() == {"username": "ada", "role": "user"}
```

Удалить `test_duplicate_register_keeps_existing_session` (дубль signup больше не создаёт 409 с живой сессией). Вместо него:

```python
def test_signup_does_not_create_or_set_cookie(indexed):
    with _session_client(indexed) as client:
        r = client.post(
            "/api/v1/auths/signup",
            json={"username": "ada", "password": "password1"},
        )
        assert r.status_code == 403
        assert r.cookies.get("ragkb_session") is None
        assert client.get("/api/v1/auths/me").status_code == 401
```

Удалить `test_short_password_rejected` (проверка 422 живёт в `test_create_rejects_short_password_and_bad_role`).

`test_session_admin_rebuild_and_bootstrap`:

```python
def test_session_admin_rebuild_and_bootstrap(indexed):
    _seed_user(database_url(), "ada", role="admin")
    with _session_client(indexed) as client:
        assert (
            client.post(
                "/api/v1/auths/signin",
                json={"username": "ada", "password": "password1"},
            ).status_code
            == 200
        )
        assert client.get("/api/v1/auths/me").json() == {"username": "ada", "role": "admin"}
        names = [
            row["name"] for row in client.get("/api/v1/admin/documents").json()["corpus"]
        ]
        accepted = client.post("/api/v1/admin/documents/accept", json={"names": names})
        assert accepted.status_code == 200
        assert client.post("/api/v1/index/rebuild").status_code == 200
        boot = client.get(
            "/api/v1/bootstrap",
            params={"session_id": "00000000-0000-4000-8000-000000000003"},
        )
        assert boot.status_code == 200
        assert boot.json()["user"]["is_admin"] is True
        assert boot.json()["capabilities"]["reindex"] is True
```

`test_session_history_disabled_does_not_persist_chats`:

```python
def test_session_history_disabled_does_not_persist_chats(indexed):
    indexed.database_url = database_url()
    indexed.auth.mode = "session"
    indexed.history.enabled = False
    _seed_user(database_url(), "ada")
    with TestClient(make_app(indexed)) as client:
        assert (
            client.post(
                "/api/v1/auths/signin",
                json={"username": "ada", "password": "password1"},
            ).status_code
            == 200
        )
        created = client.post("/api/v1/organization/acme/chat_conversations")
        assert created.status_code == 200
        assert created.json().get("conversation_id")
    engine = create_engine(alembic_sync_url(database_url()))
    with engine.connect() as conn:
        n = conn.execute(text("SELECT COUNT(*) FROM conversations")).scalar()
        users = conn.execute(text("SELECT COUNT(*) FROM users")).scalar()
    engine.dispose()
    assert n == 0
    assert users == 1
```

Проверить `rg "/auths/signup"` в `backend/tests`: единственные оставшиеся вызовы — тесты 403.

- [ ] **Step 6: Run tests**

Run: `cd backend && uv run pytest tests/test_guard.py tests/test_admin_http.py -q --tb=short`

Expected: PASS

Если задан `RAGKB_TEST_DATABASE_URL`:

Run: `cd backend && uv run pytest tests/test_session_auth.py -q --tb=short`

Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add backend/ragkb/api/routes/auths.py \
  backend/ragkb/services/auth.py \
  backend/tests/test_guard.py \
  backend/tests/test_session_auth.py
git commit -m "$(cat <<'EOF'
Return 403 from public signup; tests seed accounts instead.

EOF
)"
```

---

### Task 3: BFF и страницы

**Files:**
- Modify: `frontend/src/lib/server/backend.js`
- Modify: `frontend/src/routes/api/admin/users/+server.js`
- Modify: `frontend/src/routes/admin/users/+page.svelte`
- Modify: `frontend/src/routes/register/+page.svelte`

**Interfaces:**
- Consumes: FastAPI `POST /api/v1/admin/users` 201; `POST /api/v1/auths/signup` 403
- Produces: браузерный `POST /api/admin/users`; форма на `/admin/users`; `/register` без полей. Хук: `/register` остаётся в `PUBLIC`

- [ ] **Step 1: Forward upstream status from `proxyJson`**

В `frontend/src/lib/server/backend.js` в `proxyJson` успешный ответ:

```javascript
	return json(await upstream.json(), { status: upstream.status });
```

Иначе 201 с бэкенда станет 200. Остальные успешные ручки по-прежнему 200.

- [ ] **Step 2: BFF POST**

`frontend/src/routes/api/admin/users/+server.js` — к существующему `GET` добавить:

```javascript
export async function POST({ request }) {
	return proxyJson('/admin/users', request, {
		method: 'POST',
		body: await request.text()
	});
}
```

BFF `POST /api/auths/signup` не менять: он уже проксирует тело и вернёт 403.

- [ ] **Step 3: Admin form**

В `frontend/src/routes/admin/users/+page.svelte` после `pending` добавить состояние формы и `create`:

```javascript
	let newName = $state('');
	let newPassword = $state('');
	let newRole = $state('user');

	async function create() {
		if (pending) return;
		pending = 'create';
		error = '';
		try {
			const response = await fetch('/api/admin/users', {
				method: 'POST',
				credentials: 'include',
				headers: { 'content-type': 'application/json' },
				body: JSON.stringify({
					username: newName,
					password: newPassword,
					role: newRole
				})
			});
			const body = await response.json().catch(() => ({}));
			if (!response.ok) {
				error = typeof body.detail === 'string' ? body.detail : 'Не удалось создать пользователя';
				return;
			}
			users = [...users, body];
			newName = '';
			newPassword = '';
			newRole = 'user';
		} catch (err) {
			error = String(err);
		} finally {
			pending = null;
		}
	}
```

`pending` уже `string | null` для имени при смене роли — `'create'` не пересечётся с username. В `setRole` оставить `if (pending) return`.

Над `<table>` (после блока `{#if error}`):

```svelte
<form
	class="mb-4 flex max-w-lg flex-col gap-2"
	onsubmit={(event) => {
		event.preventDefault();
		create();
	}}
>
	<h2 class="text-base font-medium">Создать</h2>
	<label class="flex flex-col gap-1 text-sm text-stone-500 dark:text-stone-400">
		Имя пользователя
		<input class="field" name="username" autocomplete="off" bind:value={newName} required />
	</label>
	<label class="flex flex-col gap-1 text-sm text-stone-500 dark:text-stone-400">
		Пароль
		<input
			class="field"
			name="password"
			type="password"
			autocomplete="new-password"
			bind:value={newPassword}
			required
		/>
	</label>
	<label class="flex flex-col gap-1 text-sm text-stone-500 dark:text-stone-400">
		Роль
		<select class="field" bind:value={newRole}>
			<option value="user">user</option>
			<option value="admin">admin</option>
		</select>
	</label>
	<button class="btn-accent self-start" type="submit" disabled={pending !== null}>Создать</button>
</form>
```

Кнопки смены роли: `disabled={pending === user.username}` оставить; пока `pending === 'create'`, они тоже не жмутся из-за `if (pending) return` в `setRole`.

- [ ] **Step 4: Register page without a form**

Заменить содержимое `frontend/src/routes/register/+page.svelte` на:

```svelte
<svelte:head>
	<title>Регистрация — База знаний</title>
</svelte:head>

<div class="flex min-h-dvh items-center justify-center p-4">
	<div
		class="flex w-full max-w-sm flex-col items-center gap-1.5 rounded-xl border border-stone-300 bg-white p-6 dark:border-stone-700 dark:bg-stone-900"
	>
		<img class="mb-1.5 rounded-2xl" src="/logo.png" alt="" width="72" height="72" />
		<h1 class="m-0 text-xl text-red-600 dark:text-red-400">База знаний</h1>
		<p class="m-0 mb-3 text-center text-sm text-stone-500 dark:text-stone-400">
			Учётку создаёт администратор. Самостоятельная регистрация закрыта.
		</p>
		<p class="mt-3 text-sm"><a class="hover:underline" href="/login">Войти</a></p>
	</div>
</div>
```

`/login` ссылку «Регистрация» не трогать. `frontend/src/hooks.server.js` — `PUBLIC` по-прежнему содержит `/register`.

- [ ] **Step 5: Check frontend**

Run: `cd frontend && bun run check`

Expected: PASS (или только прежние ошибки, не из этих файлов)

Вручную: админ логинится → `/admin/users` создаёт `eve` / `user` → выйти → войти как `eve`. `/register` без полей. `POST /api/auths/signup` в DevTools → 403.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/lib/server/backend.js \
  frontend/src/routes/api/admin/users/+server.js \
  frontend/src/routes/admin/users/+page.svelte \
  frontend/src/routes/register/+page.svelte
git commit -m "$(cat <<'EOF'
Add admin user form and close self-serve registration UI.

EOF
)"
```

---

### Task 4: Живые доки и статус спеки

**Files:**
- Modify: `README.md`
- Modify: `AGENTS.md`
- Modify: `frontend/README.md`
- Modify: `docs/OpenAPI 3.0.0 Спецификация — Auth API для RAG-системы.yml`
- Modify: `docs/superpowers/specs/2026-09-10-admin-create-users-design.md`

**Interfaces:**
- Consumes: контракт из спеки (signup 403; людей заводит админ)
- Produces: живые доки без «зарегистрируйтесь на /register»

- [ ] **Step 1: README**

В быстром старте:

```
Compose (`docker compose up` / `make up`): `RAGKB_AUTH_MODE=session` —
войдите на `/login` (учётку создаёт администратор). `RAGKB_DEV_USER` сессию
не заменяет.
```

В блоке про Angie оставить `/login`, `/register`, `/api/auths` как пути без OIDC (страница `/register` жива).

Строка про исключения без куки:

```
При `RAGKB_AUTH_MODE=session` (compose) все эндпоинты, кроме `/health`,
`POST /api/v1/auths/signup` и `POST /api/v1/auths/signin`, требуют сессионную куку и без
неё отвечают `401`. `POST /api/v1/auths/signup` без куки отвечает `403` (регистрация
закрыта). Режим `proxy` по-прежнему читает `X-Forwarded-*`.
```

В таблицу HTTP API к строке signup (если есть) или рядом с auth: signup закрыт; создание — `POST /api/v1/admin/users`.

- [ ] **Step 2: AGENTS.md и frontend/README.md**

`AGENTS.md` (блок «Чего не делать» / compose):

```
- Compose: `RAGKB_AUTH_MODE=session`, вход формой `/login` (учётку создаёт
  админ на `/admin/users`). `/register` остаётся публичной страницей-пояснением.
  `RAGKB_DEV_USER` сессию не заменяет. На сервере Angie не должен требовать
  OIDC на `/login`, `/register`, `/api/auths`. oauth2-proxy и Keycloak в стеке нет.
```

`frontend/README.md` — Angie по-прежнему не требует OIDC на `/login`, `/register`, `/api/auths`.

- [ ] **Step 3: OpenAPI signup**

В `docs/OpenAPI 3.0.0 Спецификация — Auth API для RAG-системы.yml` у `POST /api/v1/auths/signup`:

- `summary`: Регистрация закрыта
- `description`: всегда 403, пользователя не создаёт, куку не ставит. Учётку создаёт `POST /api/v1/admin/users`.
- `requestBody` сделать не обязательным или убрать
- `responses`: `'403'` с `detail: регистрация закрыта, учётку создаёт администратор`; убрать 200/409 как успех создания

- [ ] **Step 4: Spec status**

В шапке `docs/superpowers/specs/2026-09-10-admin-create-users-design.md`: `Статус | готово`.

- [ ] **Step 5: Commit**

```bash
git add README.md AGENTS.md frontend/README.md \
  "docs/OpenAPI 3.0.0 Спецификация — Auth API для RAG-системы.yml" \
  docs/superpowers/specs/2026-09-10-admin-create-users-design.md
git commit -m "$(cat <<'EOF'
Document closed signup and admin-created accounts.

EOF
)"
```

---

## Spec coverage (self-review)

| Спека | Задача |
|---|---|
| signup всегда 403, без тела, без куки | Task 2 |
| `POST /admin/users` 201, роль, 409/422/403 | Task 1 |
| сессия админа жива | Task 1 `test_admin_creates_user` |
| BFF POST users; signup BFF без правок | Task 3 |
| форма `/admin/users` | Task 3 |
| `/register` без формы; ссылка с `/login` | Task 3 |
| `ensure-admin` / `GET /users` / чужой пароль | не делаем |
| README, AGENTS, OpenAPI | Task 4 |
| фикстуры без signup | Task 2 |
