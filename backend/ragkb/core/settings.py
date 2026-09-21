"""Пользовательские настройки поверх конфигурации.

Значения по умолчанию живут в `Settings`, окружение (`RAGKB_*`) их
перекрывает, а интерфейс правит третий слой — файл переопределений
(`settings_file`, по умолчанию `data/settings.json`). При старте сервиса
файл накладывается поверх конфигурации, поэтому правка из интерфейса
переживает перезапуск.

Здесь же — каталог полей, которые вообще можно править: он же отдаётся
странице настроек, чтобы она не знала про `Settings` ничего. Поля, меняющие
смысл индекса (модель эмбеддингов, нарезка, хранилище), помечены требованием
`reindex`; поля, которые читаются один раз при старте процесса, — `restart`.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from .config import Settings
from .errors import InvalidRequest

Kind = Literal["text", "number", "boolean", "select", "secret", "textarea"]
Requires = Literal["reindex", "restart"]


@dataclass(frozen=True)
class Field:
    """Одно редактируемое поле: путь в конфигурации и подсказки для интерфейса."""

    path: str
    label: str
    group: str
    kind: Kind = "text"
    help: str = ""
    options: tuple[str, ...] = ()
    minimum: float | None = None
    maximum: float | None = None
    requires: Requires | None = None
    secret: bool = False
    # Разрешено ли снять переопределение и вернуться к значению окружения.
    resettable: bool = True
    extra: dict[str, Any] = field(default_factory=dict)


def _f(path: str, label: str, group: str, **kwargs: Any) -> Field:
    return Field(path=path, label=label, group=group, **kwargs)


FIELDS: tuple[Field, ...] = (
    # ------------------------------------------------------------- эмбеддинги
    _f(
        "embedding.backend",
        "Бэкенд",
        "Эмбеддинги",
        kind="select",
        options=("ollama", "fake"),
        help="fake — детерминированные векторы без сети, только для тестов",
        requires="reindex",
    ),
    _f(
        "embedding.model",
        "Модель",
        "Эмбеддинги",
        help="Тег модели в Ollama, например qwen3-embedding:0.6b",
        requires="reindex",
    ),
    _f(
        "embedding.base_url",
        "Адрес Ollama",
        "Эмбеддинги",
        help="Корень API без /v1: эмбеддинги берутся из /api/embed",
    ),
    _f("embedding.keep_alive", "Держать модель загруженной", "Эмбеддинги", help="Например 30m"),
    _f(
        "embedding.timeout",
        "Таймаут запроса, с",
        "Эмбеддинги",
        kind="number",
        minimum=5,
        maximum=3600,
        help="Первый запрос поднимает модель в память — на холодную это долго",
    ),
    _f(
        "embedding.fake_dim",
        "Размерность fake-бэкенда",
        "Эмбеддинги",
        kind="number",
        minimum=8,
        maximum=4096,
        help="Только для бэкенда fake: детерминированные векторы для тестов",
        requires="reindex",
    ),
    _f(
        "embedding.num_ctx",
        "Контекст модели",
        "Эмбеддинги",
        kind="number",
        minimum=0,
        maximum=131072,
        help="0 — не переопределять контекст модели",
    ),
    # ------------------------------------------------------------------ поиск
    _f(
        "retrieval.top_k",
        "Фрагментов в ответ",
        "Поиск",
        kind="number",
        minimum=1,
        maximum=20,
    ),
    _f(
        "retrieval.candidates",
        "Кандидатов до слияния",
        "Поиск",
        kind="number",
        minimum=1,
        maximum=200,
        help="Сколько берёт каждая половина поиска: больше — выше recall, дороже MMR",
    ),
    _f("retrieval.use_dense", "Плотный поиск", "Поиск", kind="boolean"),
    _f("retrieval.use_bm25", "Лексический поиск (BM25)", "Поиск", kind="boolean"),
    _f(
        "retrieval.dense_weight",
        "Вес плотного поиска",
        "Поиск",
        kind="number",
        minimum=0,
        maximum=10,
        help="Вклад в слияние RRF; 0 выбрасывает половину из слияния",
    ),
    _f(
        "retrieval.bm25_weight",
        "Вес лексического поиска",
        "Поиск",
        kind="number",
        minimum=0,
        maximum=10,
    ),
    _f(
        "retrieval.rrf_k",
        "Константа RRF",
        "Поиск",
        kind="number",
        minimum=1,
        maximum=1000,
        help="Больше — ровнее вклад низких рангов (в статье 60)",
    ),
    _f("retrieval.use_mmr", "MMR: разнообразие выдачи", "Поиск", kind="boolean"),
    _f(
        "retrieval.mmr_lambda",
        "Лямбда MMR",
        "Поиск",
        kind="number",
        minimum=0,
        maximum=1,
        help="1 — только релевантность, 0 — только разнообразие",
    ),
    _f(
        "retrieval.min_score",
        "Порог близости",
        "Поиск",
        kind="number",
        minimum=0,
        maximum=1,
        help="Ниже порога система отвечает «нет информации»; 0 — выключен",
    ),
    _f(
        "retrieval.reranker",
        "Реранкер",
        "Поиск",
        kind="select",
        options=("none", "http"),
        help="http — внешний сервис по адресу ниже (Jina/Cohere-совместимый)",
    ),
    _f("retrieval.reranker_url", "Адрес реранкера", "Поиск"),
    _f("retrieval.reranker_model", "Модель реранкера", "Поиск"),
    _f(
        "retrieval.reranker_timeout",
        "Таймаут реранкера, с",
        "Поиск",
        kind="number",
        minimum=1,
        maximum=600,
    ),
    _f(
        "retrieval.min_rerank_score",
        "Порог реранкера",
        "Поиск",
        kind="number",
        minimum=0,
        maximum=1,
        help="Шкала у каждой модели своя: включать после замера",
    ),
    # ------------------------------------------------------------------ чанки
    _f(
        "chunking.size",
        "Размер чанка, символов",
        "Нарезка",
        kind="number",
        minimum=100,
        maximum=4000,
        requires="reindex",
    ),
    _f(
        "chunking.overlap",
        "Перехлёст, символов",
        "Нарезка",
        kind="number",
        minimum=0,
        maximum=1000,
        requires="reindex",
    ),
    # -------------------------------------------------------------- хранилище
    _f(
        "store.backend",
        "Хранилище",
        "Хранилище",
        kind="select",
        options=("chroma", "memory"),
        help="memory живёт только внутри процесса — для тестов",
        requires="reindex",
    ),
    _f(
        "store.collection",
        "Коллекция",
        "Хранилище",
        requires="reindex",
    ),
    _f("store.chroma_host", "Сервер Chroma", "Хранилище", help="Пусто — встроенный режим"),
    _f(
        "store.chroma_port",
        "Порт Chroma",
        "Хранилище",
        kind="number",
        minimum=1,
        maximum=65535,
    ),
    _f(
        "store.hnsw_search_ef",
        "HNSW: полнота поиска",
        "Хранилище",
        kind="number",
        minimum=10,
        maximum=2000,
        help="Больше — выше recall и медленнее; менять после замера eval.py",
        requires="reindex",
    ),
    _f(
        "store.hnsw_construction_ef",
        "HNSW: качество сборки",
        "Хранилище",
        kind="number",
        minimum=10,
        maximum=2000,
        requires="reindex",
    ),
    _f(
        "store.hnsw_m",
        "HNSW: связей на узел",
        "Хранилище",
        kind="number",
        minimum=2,
        maximum=128,
        requires="reindex",
    ),
    # --------------------------------------------------------------- генерация
    _f(
        "llm.backend",
        "Источник списка моделей",
        "Генерация",
        kind="select",
        options=("openai", "ollama", "static"),
        help="Меняется при старте: каталог моделей собирается один раз",
        requires="restart",
    ),
    _f("llm.model", "Модель", "Генерация"),
    _f(
        "llm.base_url",
        "Адрес модели",
        "Генерация",
        help="OpenAI-совместимый HTTP, обычно корень с /v1; без него вопросы отклоняются",
    ),
    _f("llm.api_key", "Ключ API", "Генерация", kind="secret", secret=True),
    _f(
        "llm.temperature",
        "Температура",
        "Генерация",
        kind="number",
        minimum=0,
        maximum=2,
    ),
    _f(
        "llm.max_tokens",
        "Максимум токенов ответа",
        "Генерация",
        kind="number",
        minimum=16,
        maximum=32768,
    ),
    _f("llm.timeout", "Таймаут, с", "Генерация", kind="number", minimum=5, maximum=3600),
    # ------------------------------------------------------------- организация
    _f("organization.name", "Название", "Организация"),
    _f("organization.id", "Идентификатор", "Организация"),
    _f(
        "organization.description",
        "Описание",
        "Организация",
        kind="textarea",
    ),
    # -------------------------------------------------------------------- логи
    _f(
        "logging.level",
        "Уровень",
        "Логи",
        kind="select",
        options=("DEBUG", "INFO", "WARNING", "ERROR"),
    ),
)

FIELDS_BY_PATH: dict[str, Field] = {item.path: item for item in FIELDS}
GROUP_ORDER: tuple[str, ...] = (
    "Эмбеддинги",
    "Поиск",
    "Нарезка",
    "Хранилище",
    "Генерация",
    "Организация",
    "Логи",
)

# Поля, которые показываем странице, но править нельзя: они задают, где лежат
# данные и как сервис подключён к БД.
READONLY: tuple[tuple[str, str, str], ...] = (
    (
        "docs_dir",
        "Каталог документов",
        "Корпус читается отсюда; меняется переменной RAGKB_DOCS_DIR",
    ),
    ("index_dir", "Каталог индекса", "Здесь лежат коллекция Chroma и манифест"),
    ("settings_file", "Файл настроек", "Сюда пишутся значения со страницы настроек"),
    (
        "database_url",
        "База данных",
        "Пусто — реестр выключен, индексируется весь каталог",
    ),
)


# ------------------------------------------------------------------ окружение


def _env_by_path() -> dict[str, str]:
    """Обратный индекс «путь в конфигурации → переменная окружения»."""
    mapping: dict[str, str] = {}
    for env, (section, attr) in Settings.env_overrides().items():
        mapping[f"{section}.{attr}" if section else attr] = env
    return mapping


ENV_BY_PATH: dict[str, str] = _env_by_path()


def _target(cfg: Settings, path: str) -> tuple[Any, str]:
    """Разбирает путь «раздел.поле»; у верхнеуровневых полей раздела нет."""
    section, separator, attr = path.partition(".")
    if separator:
        return getattr(cfg, section), attr
    return cfg, section


def value_at(cfg: Settings, path: str) -> Any:
    target, attr = _target(cfg, path)
    return getattr(target, attr)


def set_value(cfg: Settings, path: str, value: Any) -> None:
    target, attr = _target(cfg, path)
    setattr(target, attr, value)


def source_of(path: str, overrides: dict[str, Any]) -> str:
    """Откуда взялось значение: интерфейс, окружение или умолчание."""
    if path in overrides:
        return "settings"
    if path in ENV_BY_PATH:
        import os

        if os.environ.get(ENV_BY_PATH[path]):
            return "env"
    return "default"


# ------------------------------------------------------------------- валидация


def coerce(item: Field, value: Any) -> Any:
    """Приводит значение из формы к типу поля. Ошибка — 400 с понятным текстом."""
    if item.kind == "boolean":
        if isinstance(value, bool):
            return value
        if isinstance(value, str) and value.lower() in {"true", "false"}:
            return value.lower() == "true"
        raise InvalidRequest(f"«{item.label}»: ожидается да/нет")
    if item.kind == "number":
        try:
            number = float(value)
        except (TypeError, ValueError) as exc:
            raise InvalidRequest(f"«{item.label}»: ожидается число") from exc
        if item.minimum is not None and number < item.minimum:
            raise InvalidRequest(f"«{item.label}»: не меньше {item.minimum:g}")
        if item.maximum is not None and number > item.maximum:
            raise InvalidRequest(f"«{item.label}»: не больше {item.maximum:g}")
        # Целые поля не должны превращаться в 1.0: pydantic потом ругается.
        return int(number) if number.is_integer() and isinstance(value, (int, str)) else number
    if item.kind == "select":
        text = str(value)
        if text not in item.options:
            raise InvalidRequest(
                f"«{item.label}»: допустимые значения — {', '.join(item.options)}"
            )
        return text
    return "" if value is None else str(value)


def requirements(paths: list[str]) -> dict[str, bool]:
    """Что потребуется после смены этих полей."""
    return {
        "reindex": any(
            FIELDS_BY_PATH[p].requires == "reindex" for p in paths if p in FIELDS_BY_PATH
        ),
        "restart": any(
            FIELDS_BY_PATH[p].requires == "restart" for p in paths if p in FIELDS_BY_PATH
        ),
    }


# ------------------------------------------------------------------ файл


def read_overrides(path: str | Path) -> dict[str, Any]:
    """Читает файл переопределений. Битый файл — не повод не запуститься."""
    file = Path(path)
    if not file.exists():
        return {}
    try:
        payload = json.loads(file.read_text(encoding="utf-8"))
    except ValueError:
        return {}
    if not isinstance(payload, dict):
        return {}
    return {str(key): value for key, value in payload.items() if str(key) in FIELDS_BY_PATH}


def write_overrides(path: str | Path, overrides: dict[str, Any]) -> None:
    file = Path(path)
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_text(
        json.dumps(overrides, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def apply_overrides(cfg: Settings, overrides: dict[str, Any]) -> list[str]:
    """Накладывает переопределения на конфигурацию. Возвращает применённые пути.

    Значение может не подойти текущей модели (например, файл правили руками):
    такое поле пропускаем и сообщаем вызывающему, а не роняем старт сервиса.
    """
    applied: list[str] = []
    for path, raw in overrides.items():
        item = FIELDS_BY_PATH.get(path)
        if item is None:
            continue
        try:
            set_value(cfg, path, coerce(item, raw))
        except (InvalidRequest, AttributeError, TypeError):
            continue
        applied.append(path)
    return applied


def masked(item: Field, value: Any) -> Any:
    """Секреты наружу не отдаём: только признак «задан»."""
    if item.secret:
        return "***" if value else ""
    return value


def masked_value(cfg: Settings, path: str) -> Any:
    """Значение только для показа: пароль в строке подключения скрываем."""
    value = value_at(cfg, path)
    if path == "database_url":
        return _hide_password(str(value))
    return value


def _hide_password(url: str) -> str:
    if not url or "@" not in url:
        return url
    scheme, _, rest = url.partition("://")
    credentials, _, host = rest.rpartition("@")
    user, separator, _password = credentials.partition(":")
    if not separator:
        return url
    return f"{scheme}://{user}:***@{host}"
