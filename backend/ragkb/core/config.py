"""Конфигурация системы. Всё настраивается через YAML или переменные окружения."""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Any

# Общий путь к YAML: uvicorn, Alembic и локальный запуск читают одно и то же.
DEFAULT_CONFIG = "config.yaml"


@dataclass
class ChunkConfig:
    # Размер чанка в символах. ~800 символов ≈ 200-250 токенов для русского текста.
    size: int = 900
    overlap: int = 150
    # Не резать чанки короче — такие куски склеиваются с соседями.
    min_size: int = 120
    # Уважать границы структуры (заголовки, абзацы) при нарезке.
    respect_structure: bool = True


@dataclass
class EmbeddingConfig:
    # backend: "openai" | "sentence-transformers" | "tfidf" | "ollama"
    backend: str = "tfidf"
    model: str = "bge-m3"
    # OpenAI-совместимый корень, обычно …/v1. Пусто — задайте RAGKB_EMBEDDING_URL.
    base_url: str = ""
    api_key: str = ""
    batch_size: int = 32
    # e5-модели требуют префиксов "query: " / "passage: "
    query_prefix: str = ""
    doc_prefix: str = ""
    # Размерность для tfidf-фолбэка
    tfidf_dim: int = 4096


@dataclass
class StoreConfig:
    # backend: "chroma" | "numpy"
    backend: str = "chroma"
    collection: str = "knowledge_base"
    # Пусто — встроенный режим (файлы рядом с индексом).
    # Заполнено — подключение к отдельному серверу Chroma.
    chroma_host: str = ""
    chroma_port: int = 8000
    upsert_batch: int = 500
    # Параметры HNSW. construction_ef и M влияют на качество индекса и время
    # сборки, search_ef — на полноту поиска в рантайме.
    hnsw_construction_ef: int = 200
    hnsw_search_ef: int = 100
    hnsw_m: int = 16


@dataclass
class RetrievalConfig:
    top_k: int = 5              # сколько чанков уходит в промпт
    candidates: int = 30        # сколько кандидатов достаём до реранка
    use_bm25: bool = True
    use_dense: bool = True
    rrf_k: int = 60             # константа Reciprocal Rank Fusion
    # MMR — снижает дублирование в выдаче. 1.0 = только релевантность, 0.0 = только разнообразие.
    mmr_lambda: float = 0.7
    use_mmr: bool = True
    # Порог косинусной близости: ниже — считаем, что ответа в базе нет.
    min_score: float = 0.0
    # Реранкер (cross-encoder). "none" | "sentence-transformers"
    reranker: str = "none"
    reranker_model: str = "BAAI/bge-reranker-v2-m3"


@dataclass
class LLMConfig:
    # backend: "openai" | "extractive" | "ollama"
    backend: str = "extractive"
    model: str = "qwen2.5:7b-instruct"
    # OpenAI-совместимый корень, обычно …/v1. Пусто — задайте RAGKB_LLM_URL.
    base_url: str = ""
    api_key: str = ""
    temperature: float = 0.1
    max_tokens: int = 1024
    timeout: int = 180
    # Пустой available — можно выбрать всё, что отдал GET /models сервера.
    # Заполненный — подмножество. Свободный ввод недопустим.
    available: list[dict[str, str]] = field(default_factory=list)


@dataclass
class AuthConfig:
    # mode: "proxy" — логин приходит заголовком от reverse proxy (Angie)
    #       "disabled" — аутентификации нет, всё работает от имени anonymous
    # По умолчанию закрыто: забытая настройка должна давать отказ,
    # а не открытый наружу сервис.
    mode: str = "proxy"
    # Заголовки семейства X-Forwarded-*, которые прокси передаёт наверх.
    # НЕ X-Auth-Request-*: те выставляются в заголовки ответа для режима
    # nginx/Angie auth_request.
    header: str = "X-Forwarded-Preferred-Username"
    email_header: str = "X-Forwarded-Email"
    groups_header: str = "X-Forwarded-Groups"
    admin_group: str = "ragkb-admins"


@dataclass
class OrganizationConfig:
    """Кто владеет этой установкой сервиса.

    Одна установка обслуживает одну организацию: разграничения базы знаний
    внутри сервиса нет, разные организации разводятся разными развёртываниями.
    Эти сведения нужны интерфейсу, чтобы подписать, чья это база.
    """

    # Пусто — организация не настроена; тогда /organizations отдаёт пустой
    # список, а не организацию без имени.
    name: str = ""
    # Идентификатор для программных клиентов. Пуст — берётся имя.
    id: str = ""
    description: str = ""


@dataclass
class HistoryConfig:
    # Хранение переписки пользователей. Выключается только через config.yaml —
    # см. комментарий о переменных окружения ниже.
    enabled: bool = True
    path: str = "data/history.sqlite3"
    # Срок хранения диалогов. Сервис хранит персональные данные: журнал
    # вопросов сотрудника есть сведения о нём.
    retention_days: int = 90
    # Сколько последних ходов уходит в _condense при переформулировке вопроса.
    window: int = 3


@dataclass
class Config:
    # Где лежат исходные документы и где хранится индекс.
    docs_dir: str = "data/docs"
    index_dir: str = "data/index"
    language: str = "ru"
    chunking: ChunkConfig = field(default_factory=ChunkConfig)
    embedding: EmbeddingConfig = field(default_factory=EmbeddingConfig)
    store: StoreConfig = field(default_factory=StoreConfig)
    retrieval: RetrievalConfig = field(default_factory=RetrievalConfig)
    llm: LLMConfig = field(default_factory=LLMConfig)
    auth: AuthConfig = field(default_factory=AuthConfig)
    organization: OrganizationConfig = field(default_factory=OrganizationConfig)
    history: HistoryConfig = field(default_factory=HistoryConfig)

    @classmethod
    def load(cls, path: str | os.PathLike | None = None) -> Config:
        _load_dotenv(path)
        data: dict[str, Any] = {}
        if path and Path(path).exists():
            text = Path(path).read_text(encoding="utf-8")
            data = (
                _load_yaml(text)
                if str(path).endswith((".yaml", ".yml"))
                else json.loads(text)
            )
        cfg = cls.from_dict(data)
        cfg._apply_env()
        return cfg

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Config:
        sections = {
            "chunking": ChunkConfig,
            "embedding": EmbeddingConfig,
            "store": StoreConfig,
            "retrieval": RetrievalConfig,
            "llm": LLMConfig,
            "auth": AuthConfig,
            "history": HistoryConfig,
            "organization": OrganizationConfig,
        }
        # Известные скалярные поля верхнего уровня (docs_dir, index_dir, ...).
        known_top_level = {f.name for f in fields(cls)}
        kwargs: dict[str, Any] = {}
        for key, value in (data or {}).items():
            if key in sections:
                kwargs[key] = sections[key](**value)
            elif key in known_top_level:
                kwargs[key] = value
            # Неизвестный корневой ключ молча игнорируем: это защита на случай,
            # если _mini_yaml (фолбэк без pyyaml) не смог правильно разобрать
            # часть файла — например, элементы YAML-последовательности,
            # которые он не умеет разбирать и пропускает в корень. Новое поле
            # конфигурации не должно ронять сервис при отсутствии pyyaml.
        return cls(**kwargs)

    def _apply_env(self) -> None:
        """Переменные окружения перекрывают файл: RAGKB_LLM_BACKEND, RAGKB_EMBEDDING_MODEL и т.д."""
        mapping = {
            "RAGKB_DOCS_DIR": ("docs_dir", self),
            "RAGKB_INDEX_DIR": ("index_dir", self),
            "RAGKB_EMBEDDING_BACKEND": ("backend", self.embedding),
            "RAGKB_EMBEDDING_MODEL": ("model", self.embedding),
            "RAGKB_EMBEDDING_URL": ("base_url", self.embedding),
            "RAGKB_EMBEDDING_API_KEY": ("api_key", self.embedding),
            "RAGKB_STORE_BACKEND": ("backend", self.store),
            "RAGKB_CHROMA_HOST": ("chroma_host", self.store),
            "RAGKB_CHROMA_COLLECTION": ("collection", self.store),
            "RAGKB_LLM_BACKEND": ("backend", self.llm),
            "RAGKB_LLM_MODEL": ("model", self.llm),
            "RAGKB_LLM_URL": ("base_url", self.llm),
            "RAGKB_LLM_API_KEY": ("api_key", self.llm),
            "RAGKB_AUTH_MODE": ("mode", self.auth),
            "RAGKB_AUTH_HEADER": ("header", self.auth),
            "RAGKB_AUTH_GROUPS_HEADER": ("groups_header", self.auth),
            "RAGKB_AUTH_EMAIL_HEADER": ("email_header", self.auth),
            "RAGKB_AUTH_ADMIN_GROUP": ("admin_group", self.auth),
            # Только путь: _apply_env присваивает значение строкой, поэтому
            # булево enabled и числовые retention_days/window сюда добавлять
            # нельзя — "false" истинна, а число станет строкой.
            "RAGKB_HISTORY_PATH": ("path", self.history),
            "RAGKB_ORG_NAME": ("name", self.organization),
            "RAGKB_ORG_ID": ("id", self.organization),
        }
        for env, (attr, target) in mapping.items():
            val = os.environ.get(env)
            if val:
                setattr(target, attr, val)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _load_dotenv(path: str | os.PathLike | None) -> None:
    """Читает `.env` рядом с конфигом и кладёт переменные в окружение.

    Файл не коммитится (см. .gitignore): здесь живут адреса и секреты
    развёртывания. Настоящее окружение важнее файла — уже заданная переменная
    не перезаписывается. Синтаксис намеренно простейший: `KEY=VALUE`, пустые
    строки и строки с `#` пропускаются, префикс `export` не обязателен,
    кавычки снимаются. Окружение применяется позже, в _apply_env, общим
    порядком — для конфига .env и экспортированные переменные неразличимы.
    """
    if not path:
        return
    env_path = Path(path).resolve().parent / ".env"
    if not env_path.exists():
        return
    for raw in env_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export "):].lstrip()
        key, sep, value = line.partition("=")
        key = key.strip()
        if not sep or not key:
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        if key not in os.environ:
            os.environ[key] = value


def _load_yaml(text: str) -> dict[str, Any]:
    try:
        import yaml
        return yaml.safe_load(text) or {}
    except ImportError:
        return _mini_yaml(text)


def _mini_yaml(text: str) -> dict[str, Any]:
    """Минимальный парсер YAML на случай, если pyyaml не установлен.

    Поддерживает только два уровня вложенности и скалярные значения —
    ровно то, что нужно для нашего конфига.
    """
    root: dict[str, Any] = {}
    current: dict[str, Any] = root
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].rstrip()
        if not line.strip():
            continue
        stripped = line.strip()
        if stripped.startswith("-"):
            # Элемент YAML-последовательности (например, llm.available).
            # Этот парсер последовательности не понимает — пропускаем строку,
            # а не кладём её обрубок в корень словаря как отдельный ключ.
            continue
        indent = len(line) - len(line.lstrip())
        key, _, value = line.strip().partition(":")
        value = value.strip()
        if not value:
            current = {}
            root[key] = current
            continue
        target = current if indent > 0 else root
        target[key] = _coerce(value)
    return root


def _coerce(value: str) -> Any:
    low = value.lower()
    if low in {"true", "false"}:
        return low == "true"
    if low in {"null", "none", "~"}:
        return None
    for cast in (int, float):
        try:
            return cast(value)
        except ValueError:
            pass
    return value.strip("'\"")
