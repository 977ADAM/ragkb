# Admin users, Docker seed, admin UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Роль `user`/`admin` в БД, сидер админа из compose после migrate, HTTP `/admin/*`, страницы хаба и списка людей, заглушка отчётов.

**Architecture:** Роль на `UserRow`; `require_admin` в `session` смотрит `role == "admin"`. Сидер — одноразовый сервис compose `ensure-admin` с `condition: service_completed_successfully`. UI ходит только в BFF `/api/admin/*`.

**Tech Stack:** FastAPI, SQLAlchemy 2 async, Alembic, Argon2, SvelteKit BFF, Docker Compose.

**Спека:** `docs/superpowers/specs/2026-09-02-admin-users-design.md`

## Global Constraints

- Публичный `POST /auth/signup` не закрывать; новые пользователи всегда `role=user`.
- `users.role` только `user` или `admin`.
- Сидер не в `lifespan` и не в `Dockerfile RUN`. Compose: `ensure-admin` после `migrate`, `rag` после `ensure-admin`, оба ожидания — `service_completed_successfully`.
- Env сидера: `ADMIN_LOGIN`, `ADMIN_PASSWORD` (не обязательно `RAGKB_` префикс).
- `get_admin_credentials` в `backend/ragkb/core/security.py` — без sqlalchemy.
- `ensure_admin` в `backend/scripts/ensure_admin.py` (`async def ensure_admin`).
- Нельзя удалить себя; нельзя удалить или разжаловать последнего админа.
- `/admin/*` — сессия + `require_admin`; `{"detail": "…"}`.
- Аналитики нет: `GET /admin/reports` → `{ "status": "unavailable" }`.
- Организация не в Postgres: `GET /admin/organization` читает `OrganizationService.get()` + `links`.
- SQLAlchemy не импортировать в `ragkb/core/` кроме уже разрешённого `database.py`.
- Коммит после каждой задачи. Не пушить, пока не попросят.
- Исторические планы в `docs/superpowers/plans/` не переписывать.

## File map

**Создать**

- `backend/migrations/versions/0006_user_role.py`
- `backend/ragkb/core/security.py`
- `backend/scripts/__init__.py`
- `backend/scripts/ensure_admin.py`
- `backend/ragkb/api/routes/admin.py`
- `backend/ragkb/services/admin_users.py`
- `backend/tests/test_admin_credentials.py`
- `backend/tests/test_ensure_admin.py`
- `backend/tests/test_admin_http.py`
- `frontend/src/routes/api/admin/users/+server.js`
- `frontend/src/routes/api/admin/users/[username]/+server.js`
- `frontend/src/routes/api/admin/organization/+server.js`
- `frontend/src/routes/api/admin/reports/+server.js`
- `frontend/src/routes/admin/+page.svelte`
- `frontend/src/routes/admin/+layout.svelte` (опционально, если удобнее резать оболочку чата)
- `frontend/src/routes/admin/users/+page.svelte`
- `frontend/src/routes/admin/reports/+page.svelte`

**Менять**

- `backend/ragkb/core/database.py` — `EXPECTED_REVISION = "0006_user_role"`
- `backend/ragkb/db/models.py` — `UserRow.role`
- `backend/ragkb/domain/entities.py` — `User.role`
- `backend/ragkb/domain/ports.py` — методы списка/роли/удаления; `user_for_token_hash` с role
- `backend/ragkb/db/repos/auth.py`
- `backend/ragkb/services/auth.py` — `create_user(..., role="user")`; `me` → username+role
- `backend/ragkb/platform/auth.py` — `User.role`; `require_admin` в session
- `backend/ragkb/api/routes/auth.py` — `/me`
- `backend/ragkb/api/router.py` — include admin
- `backend/ragkb/features/bootstrap/service.py` — `is_admin` в session по `role`
- `backend/Dockerfile` — `COPY scripts ./scripts`
- `docker-compose.yml`, `Makefile`, `deploy.sh`, `.github/workflows/deploy.yml`
- `frontend/src/hooks.server.js` — `/admin` только админ
- `frontend/src/routes/+layout.svelte` — ссылка «Админ»; прятать чат-оболочку на `/admin`
- `frontend/src/lib/chat.svelte.js` — `role` / `is_admin` из bootstrap
- `.env.example` (если снова не пустой шаблон — добавить `ADMIN_*` комментарием в README если example пуст)

---

### Task 1: Миграция `role` и ORM

**Files:**
- Create: `backend/migrations/versions/0006_user_role.py`
- Modify: `backend/ragkb/core/database.py`
- Modify: `backend/ragkb/db/models.py`
- Modify: `backend/ragkb/domain/entities.py`
- Test: `backend/tests/test_architecture.py` (head)
- Test: `backend/tests/test_guard.py` sqlite signup после migrate

**Interfaces:**
- Produces: head `0006_user_role`; `User.role: str = "user"`; `UserRow.role: Mapped[str]` default `"user"`

- [ ] **Step 1: Write failing assertion**

В `test_each_alembic_revision_creates_one_table` сейчас 5 файлов. Добавить в конец списка `"users"` нельзя (роль — ALTER). Добавить отдельный тест:

```python
def test_revision_0006_alters_users_role() -> None:
    text = (MIGRATIONS / "versions" / "0006_user_role.py").read_text()
    assert "role" in text.lower()
    assert "0005_sessions" in text
```

- [ ] **Step 2: Run to see fail**

Run: `cd backend && uv run python -m pytest tests/test_architecture.py::test_revision_0006_alters_users_role tests/test_architecture.py::test_expected_revision_matches_alembic_head -q`

Expected: FAIL (нет файла / head всё ещё `0005_sessions`)

- [ ] **Step 3: Implement migration and models**

`0006_user_role.py`: `down_revision = "0005_sessions"`. SQLite: `ALTER TABLE users ADD COLUMN role TEXT NOT NULL DEFAULT 'user'`. Postgres: то же `ALTER TABLE users ADD COLUMN role TEXT NOT NULL DEFAULT 'user'`.

`EXPECTED_REVISION = "0006_user_role"`.

`User` dataclass: `role: str = "user"`. `UserRow.role` `mapped_column(Text, nullable=False, default="user", server_default="user")`. `to_domain`/`from_domain` прокидывают `role`.

`PostgresAccounts.create_user`: `UserRow(..., role="user")` пока без аргумента — в задаче 2.

- [ ] **Step 4: Tests pass**

Run: `cd backend && uv run python -m pytest tests/test_architecture.py tests/test_guard.py::test_session_auth_on_sqlite -q`

- [ ] **Step 5: Commit**

```bash
git add backend/migrations/versions/0006_user_role.py backend/ragkb/core/database.py backend/ragkb/db/models.py backend/ragkb/domain/entities.py backend/tests/test_architecture.py
git commit -m "Add users.role Alembic revision and ORM field."
```

---

### Task 2: Порт и репозиторий аккаунтов

**Files:**
- Modify: `backend/ragkb/domain/ports.py`
- Modify: `backend/ragkb/db/repos/auth.py`
- Modify: `backend/ragkb/services/auth.py`
- Test: `backend/tests/test_admin_http.py` (пока только store через sqlite migrate; HTTP в задаче 5)

**Interfaces:**
- Produces:
  - `create_user(self, username: str, password_hash: str, role: str = "user") -> str`
  - `get_by_username` → `tuple[str, str, str, str] | None`  # id, username, password_hash, role
  - `user_for_token_hash` → `tuple[str, str, str] | None`  # id, username, role
  - `list_users(self) -> list[tuple[str, str, datetime]]`  # username, role, created_at
  - `set_role(self, username: str, role: str) -> tuple[str, str, datetime] | None`
  - `delete_user(self, username: str) -> bool`
  - `count_admins(self) -> int`

- [ ] **Step 1: Failing unit on sqlite**

```python
@pytest.mark.asyncio
async def test_create_user_default_role_user(tmp_path, monkeypatch):
    # migrate sqlite, PostgresAccounts.create_user, get_by_username[-1] == "user"
```

Пока `create_user` без role в Row — после 0006 default сработает, но Python может не выставить атрибут если не в insert. Явно передавать `role`.

- [ ] **Step 2: Run fail if signature old**

- [ ] **Step 3: Implement port + repo; AuthService.register вызывает `create_user(..., role="user")`; `login` unpack 4-tuple; `me` returns `(username, role)`**

`AuthService.me` → `tuple[str, str]` (username, role).

- [ ] **Step 4: pytest sqlite + поправить `test_session_auth` / `test_guard` на `/me` JSON `{"username", "role"}`**

- [ ] **Step 5: Commit**

```bash
git commit -m "Extend account store with role and user listing."
```

---

### Task 3: `get_admin_credentials` и `ensure_admin`

**Files:**
- Create: `backend/ragkb/core/security.py`
- Create: `backend/scripts/__init__.py` (пустой)
- Create: `backend/scripts/ensure_admin.py`
- Create: `backend/tests/test_admin_credentials.py`
- Create: `backend/tests/test_ensure_admin.py`

**Interfaces:**
- Produces:
  - `get_admin_credentials() -> tuple[str, str] | None`
  - `async def ensure_admin(store: AccountStore) -> None`

- [ ] **Step 1: Failing tests**

```python
def test_get_admin_credentials_none_when_empty(monkeypatch):
    monkeypatch.delenv("ADMIN_LOGIN", raising=False)
    monkeypatch.delenv("ADMIN_PASSWORD", raising=False)
    from ragkb.core.security import get_admin_credentials
    assert get_admin_credentials() is None

def test_get_admin_credentials_normalizes_login(monkeypatch):
    monkeypatch.setenv("ADMIN_LOGIN", "Ada")
    monkeypatch.setenv("ADMIN_PASSWORD", "password1")
    from ragkb.core.security import get_admin_credentials
    assert get_admin_credentials() == ("ada", "password1")
```

`ensure_admin`: создать; второй вызов с тем же паролем не меняет hash; другой пароль — hash другой. Ловить caplog `"Admin created by system at"`.

- [ ] **Step 2: Run fail**

- [ ] **Step 3: Implement**

`get_admin_credentials`: если нет обоих непустых — `None`. Логин: `strip().lower()`, regex как `Credentials`. Пароль `8 <= len <= 128` иначе `None` + warning.

`ensure_admin`: credentials None → return. `get_by_username`; нет → `create_user(login, hash_password(pw), role="admin")` + `log.info("Admin created by system at %s", datetime.now(timezone.utc))`. Есть + `verify_password` → return. Иначе обновить hash (добавить `update_password(username, password_hash)` на порт).

Добавить в порт `update_password(self, username: str, password_hash: str) -> None`.

`scripts/ensure_admin.py`: `async def main`: Config.load, engine, PostgresAccounts, `await ensure_admin(store)`. `if __name__` asyncio.run. Выход 0 если credentials None.

- [ ] **Step 4: Tests pass**

- [ ] **Step 5: Commit**

```bash
git commit -m "Add admin credentials helper and ensure_admin seeder."
```

---

### Task 4: `require_admin` + `/me` + bootstrap

**Files:**
- Modify: `backend/ragkb/platform/auth.py`
- Modify: `backend/ragkb/api/routes/auth.py`
- Modify: `backend/ragkb/features/bootstrap/service.py`

**Interfaces:**
- `platform.auth.User`: `role: str = "user"`; в session `User(name=..., role=row[2])`
- `require_admin`: session → `user.role == "admin"` иначе Forbidden; proxy — `in_group` как сейчас; disabled — pass
- bootstrap `is_admin`: `cfg.auth.mode == "disabled" or (session and user.role == "admin") or user.in_group(admin_group)`

- [ ] **Step 1: Test me_disabled includes role user; session signup me has role user**

- [ ] **Step 2: Fail on missing key**

- [ ] **Step 3: Implement**

- [ ] **Step 4: Pass**

- [ ] **Step 5: Commit**

```bash
git commit -m "Honor session admin role in current_user, me, and bootstrap."
```

---

### Task 5: HTTP `/admin/*`

**Files:**
- Create: `backend/ragkb/services/admin_users.py`
- Create: `backend/ragkb/api/routes/admin.py`
- Modify: `backend/ragkb/api/router.py`
- Test: `backend/tests/test_admin_http.py`

**Interfaces:**
- `AdminUsersService.list/set_role/delete` с правилами последнего админа и «не себя»
- Router prefix `/admin`, `Depends(require_admin)`

`PATCH` 404 если нет пользователя; 409/403 с `detail` «нельзя разжаловать последнего админа» / «нельзя удалить себя».

`GET /admin/organization`: если org NotFound — всё равно 200 хаб? Спека: поля из конфига. Если имени нет — `name`/`id`/`description` пустые строки + links.

`GET /admin/reports` → `{"status": "unavailable"}`

- [ ] **Step 1: Failing HTTP tests на sqlite session: user 403; admin GET users; PATCH last admin 403; DELETE self 403; reports unavailable**

Нужен сидер в тесте: `ensure_admin` или прямой `create_user(..., role="admin")`.

- [ ] **Step 2: Fail**

- [ ] **Step 3: Implement service + router; include_router**

- [ ] **Step 4: Pass**

- [ ] **Step 5: Commit**

```bash
git commit -m "Add admin HTTP routes for users, organization hub, and reports stub."
```

---

### Task 6: Compose `ensure-admin` и Docker

**Files:**
- Modify: `backend/Dockerfile` — после COPY config: `COPY scripts ./scripts`
- Modify: `docker-compose.yml`
- Modify: `Makefile` `up`/`logs`/`help`
- Modify: `deploy.sh`
- Modify: `.github/workflows/deploy.yml`
- Modify: `.env.example` если файл снова шаблон; иначе `README.md` боевой блок: `ADMIN_LOGIN` / `ADMIN_PASSWORD`

**Interfaces:**
- `ensure-admin.depends_on.migrate.condition: service_completed_successfully`
- `rag.depends_on.ensure-admin.condition: service_completed_successfully`
- `restart: "no"` у ensure-admin
- command: `python -m scripts.ensure_admin`
- env: `RAGKB_DATABASE_URL` как у rag; `ADMIN_LOGIN: ${ADMIN_LOGIN:-}`; `ADMIN_PASSWORD: ${ADMIN_PASSWORD:-}`

`up`: `docker compose up -d --build postgres migrate ensure-admin rag frontend`

- [ ] **Step 1: Нет pytest на YAML — проверить глазами и `docker compose config` локально если docker есть**

- [ ] **Step 2: Implement**

- [ ] **Step 3: `docker compose config` содержит `service_completed_successfully` для ensure-admin и rag**

- [ ] **Step 4: Commit**

```bash
git commit -m "Run ensure-admin after migrate with service_completed_successfully."
```

---

### Task 7: BFF и UI

**Files:**
- Create: BFF routes listed in file map
- Modify: `frontend/src/hooks.server.js`
- Modify: `frontend/src/routes/+layout.svelte`
- Modify: `frontend/src/lib/chat.svelte.js` — сохранить `chat.user.role` / `isAdmin` из bootstrap
- Create: admin pages

**Interfaces:**
- hooks: путь `/admin` → `GET /auth/me`, если не 200 → `/login`; если `role !== 'admin'` → `/new`
- `authPage` расширить: `/admin` не грузить оболочку чата (`adminPage`)
- Шапка: `{#if chat.isAdmin}<a href="/admin">Админ</a>{/if}`
- users page: fetch `/api/admin/users`, PATCH role
- reports: статический текст + если API `unavailable`
- organization hub: fetch `/api/admin/organization`

- [ ] **Step 1: `bun run check` после страниц**

- [ ] **Step 2: Implement BFF `proxyJson`/`proxyAuth` по образцу `frontend/src/routes/api/auth/me/+server.js`**

- [ ] **Step 3: Pages**

- [ ] **Step 4: `cd frontend && bun run check`**

- [ ] **Step 5: Commit**

```bash
git commit -m "Add admin hub, users, and reports stub in the SvelteKit UI."
```

---

## Spec coverage

| Спека | Задача |
|---|---|
| `0006_user_role` | 1 |
| порт/репо/signup user | 2 |
| credentials + ensure_admin + лог | 3 |
| session require_admin, me, bootstrap reindex | 4 |
| HTTP admin users/org/reports | 5 |
| compose `service_completed_successfully` | 6 |
| UI хаб, люди, заглушка отчётов, шапка | 7 |
| не закрывать signup | 2 |
| не хранить org в PG | 5 |
| нет аналитики | 5, 7 |
