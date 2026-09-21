"""Настройки: чтение, проверка и применение правок со страницы управления.

Сценарий ничего не знает про HTTP: он отдаёт описание полей с текущими
значениями и принимает набор правок. Значения хранятся файлом (переживают
перезапуск), применяются к живой конфигурации сразу, а движок сбрасывается —
иначе поиск продолжил бы работать со старыми настройками до перезапуска.

Отдельно показываем, чем собран индекс: если после правки он разошёлся с
конфигурацией (другая модель эмбеддингов, другая нарезка), страница честно
предлагает пересобрать его, а не оставляет администратора догадываться,
почему поиск отвечает иначе.
"""
from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any

from ragkb.core import settings as core
from ragkb.core.config import Settings
from ragkb.core.embeddings import embedder_name
from ragkb.core.errors import EngineUnavailable, InvalidRequest

log = logging.getLogger("ragkb")


class SettingsService:
    def __init__(
        self,
        cfg: Settings,
        invalidate: Callable[[], None],
        index: Any | None = None,
        models: Callable[[], list[dict[str, Any]]] | None = None,
    ):
        self.cfg = cfg
        self._invalidate = invalidate
        self._index = index
        # Каталог моделей эмбеддингов: список вариантов для поля «Модель».
        self._models = models
        # Значения окружения и умолчаний: страница показывает, к чему
        # вернётся поле, если снять переопределение.
        self._defaults = Settings()

    # ------------------------------------------------------------------ чтение

    def describe(self, *, requirements: dict[str, bool] | None = None) -> dict[str, Any]:
        overrides = core.read_overrides(self.cfg.settings_file)
        groups: list[dict[str, Any]] = []
        for title in core.GROUP_ORDER:
            fields = [
                self._field_payload(item, overrides)
                for item in core.FIELDS
                if item.group == title
            ]
            if fields:
                groups.append({"title": title, "fields": fields})
        return {
            "file": str(Path(self.cfg.settings_file).expanduser().resolve()),
            "cwd": str(Path.cwd()),
            "groups": groups,
            "readonly": [
                {
                    "path": path,
                    "label": label,
                    "help": help_text,
                    "value": core.masked_value(self.cfg, path),
                }
                for path, label, help_text in core.READONLY
            ],
            "overridden": sorted(overrides),
            "index": self.index_state(),
            "requirements": requirements or {"reindex": False, "restart": False},
        }

    def _field_payload(self, item: core.Field, overrides: dict[str, Any]) -> dict[str, Any]:
        value = core.value_at(self.cfg, item.path)
        options = list(item.options)
        labels: dict[str, str] = {}
        if item.options_from:
            for option in self._available_models(item.options_from):
                model_id = str(option.get("id") or "")
                if not model_id:
                    continue
                options.append(model_id)
                label = str(option.get("label") or "")
                if label:
                    labels[model_id] = label
            if value and str(value) not in options:
                # Текущее значение показываем всегда, даже если модели уже нет
                # в Ollama: иначе поле выглядело бы пустым и непонятно почему.
                options.insert(0, str(value))
        return {
            "path": item.path,
            "label": item.label,
            "kind": item.kind,
            "help": item.help,
            "options": options,
            "option_labels": labels,
            "minimum": item.minimum,
            "maximum": item.maximum,
            "requires": item.requires,
            "secret": item.secret,
            "value": core.masked(item, value),
            "default": core.masked(item, core.value_at(self._defaults, item.path)),
            "source": core.source_of(item.path, overrides),
        }

    def _available_models(self, source: str) -> list[dict[str, Any]]:
        """Варианты для поля-списка. Каталог недоступен — список пуст."""
        if source != "embedding_models" or self._models is None:
            return []
        try:
            return list(self._models())
        except Exception as exc:
            log.warning("не удалось получить список моделей эмбеддингов: %s", exc)
            return []

    def _check_choice(self, item: core.Field, value: Any) -> None:
        """Проверяет выбор из динамического списка, если он доступен.

        Когда каталог модели не отвечает, значение принимаем: проверит его
        Ollama при индексации, а отказ по неполным данным только мешал бы
        администратору.
        """
        if not item.options_from:
            return
        available = {
            str(option.get("id") or "")
            for option in self._available_models(item.options_from)
        }
        available.discard("")
        if available and str(value) not in available:
            raise InvalidRequest(
                f"«{item.label}»: доступны — {', '.join(sorted(available))}"
            )

    def index_state(self) -> dict[str, Any]:
        """Чем собран индекс и не разошёлся ли он с текущими настройками."""
        if self._index is None:
            return {"status": "unknown"}
        try:
            stats = self._index.stats()
        except EngineUnavailable as exc:
            return {"status": "no_index", "detail": exc.detail}
        warnings = self._drift(stats)
        return {"status": "ok", "stale": bool(warnings), "warnings": warnings, **stats}

    def _drift(self, stats: dict[str, Any]) -> list[str]:
        """Расхождения между манифестом индекса и текущей конфигурацией."""
        warnings: list[str] = []
        wanted_embedder = embedder_name(self.cfg.embedding)
        if stats.get("embedder") and stats["embedder"] != wanted_embedder:
            warnings.append(
                f"индекс собран эмбеддером «{stats['embedder']}», а сейчас выбран "
                f"«{wanted_embedder}» — нужна пересборка"
            )
        if stats.get("store") and stats["store"] != self.cfg.store.backend.lower():
            warnings.append(
                f"индекс собран хранилищем «{stats['store']}», а сейчас выбрано "
                f"«{self.cfg.store.backend}» — нужна пересборка"
            )
        try:
            indexed = self._index.manifest() if self._index is not None else {}
        except (EngineUnavailable, AttributeError):
            indexed = {}
        if indexed.get("chunk_size") and indexed["chunk_size"] != self.cfg.chunking.size:
            warnings.append(
                f"индекс собран с чанком {indexed['chunk_size']} символов, сейчас "
                f"настроено {self.cfg.chunking.size} — нужна пересборка"
            )
        if (
            indexed.get("chunk_overlap") is not None
            and indexed["chunk_overlap"] != self.cfg.chunking.overlap
        ):
            warnings.append(
                f"индекс собран с перехлёстом {indexed['chunk_overlap']}, сейчас "
                f"{self.cfg.chunking.overlap} — нужна пересборка"
            )
        return warnings

    # ---------------------------------------------------------------- запись

    def update(self, values: dict[str, Any], reset: list[str] | None = None) -> dict[str, Any]:
        values = values or {}
        reset = list(reset or [])
        before = self.index_state()
        # Размер патча ограничен самим каталогом полей: неизвестные пути
        # отклоняются ниже, поэтому «слишком много полей» невозможно.
        unknown = sorted(
            path
            for path in [*values, *reset]
            if path not in core.FIELDS_BY_PATH
        )
        if unknown:
            raise InvalidRequest(
                "Неизвестные настройки: " + ", ".join(unknown)
                + ". Доступные перечисляет GET /api/v1/admin/settings"
            )

        previous_overrides = core.read_overrides(self.cfg.settings_file)
        overrides = dict(previous_overrides)
        changed: list[str] = []
        for path, raw in values.items():
            item = core.FIELDS_BY_PATH[path]
            # Пустая строка у секрета означает «оставить как есть»: value из
            # формы всегда приходит маскированным, и затирать ключ нельзя.
            if item.secret and raw in {"", "***"}:
                continue
            parsed = core.coerce(item, raw)
            self._check_choice(item, parsed)
            # «Изменилось» — это про значение, а не про факт записи в файл:
            # от этого зависят предупреждения о пересборке и перезапуске.
            if core.value_at(self.cfg, path) != parsed:
                changed.append(path)
            overrides[path] = parsed
        for path in reset:
            if overrides.pop(path, None) is not None:
                changed.append(path)

        core.write_overrides(self.cfg.settings_file, overrides)
        # Накладываем весь файл: сброшенные поля должны вернуться к значениям
        # окружения, а не остаться прежними в памяти.
        reapply(self.cfg, overrides)

        problems = core.inconsistencies(self.cfg)
        if problems:
            # Настройки записались бы в нерабочее состояние — возвращаем как было.
            core.write_overrides(self.cfg.settings_file, previous_overrides)
            reapply(self.cfg, previous_overrides)
            self._invalidate()
            raise InvalidRequest("; ".join(problems))

        if changed:
            self._invalidate()

        # «Нужна пересборка» — про состояние, а не про факт правки: возврат
        # настройки к той, которой индекс и собирался, ничего пересобирать не
        # требует, а смена настройки при отсутствующем индексе — тем более.
        after = self.index_state()
        requirements = {
            "reindex": bool(after.get("stale"))
            or (
                core.requirements(changed)["reindex"]
                and not before.get("stale")
                and after.get("status") == "ok"
            ),
            "restart": core.requirements(changed)["restart"],
        }
        payload = self.describe(requirements=requirements)
        payload["changed"] = sorted(set(changed))
        return payload


def reapply(cfg: Settings, overrides: dict[str, Any]) -> None:
    """Приводит живую конфигурацию к файлу переопределений.

    Сначала возвращаем значения из окружения и умолчаний — иначе сброшенное
    поле осталось бы прежним до перезапуска.
    """
    fresh = Settings()
    for item in core.FIELDS:
        try:
            core.set_value(cfg, item.path, core.value_at(fresh, item.path))
        except AttributeError:  # pragma: no cover — путь есть в каталоге полей
            continue
    core.apply_overrides(cfg, overrides)
