from collections.abc import Callable

from ragkb.domain.ports import ModelCatalog
from ragkb.services.models_schemas import ModelInfo


class ModelsService:
    """Каталог моделей генерации.

    `embedding_models` — модели, которые считают только векторы: в списке
    ответов им не место (выбор такой модели в чате заканчивается ошибкой
    генерации). Провайдер необязателен: без него список отдаётся как есть.
    """

    def __init__(
        self,
        catalog: ModelCatalog,
        embedding_models: Callable[[], list[dict]] | None = None,
    ):
        self.catalog = catalog
        self._embedding_models = embedding_models

    def list(self) -> list[ModelInfo]:
        hidden = self._vector_only_ids()
        items = [
            ModelInfo(
                id=item.id,
                display_name=item.display_name,
                context_window=item.context_window,
                supports_tools=item.supports_tools,
                is_default=item.is_default,
            )
            for item in self.catalog.list()
            if item.id not in hidden
        ]
        if items and not any(item.is_default for item in items):
            # Убрали модель по умолчанию — переносим признак на первую.
            items[0].is_default = True
        return items

    def _vector_only_ids(self) -> set[str]:
        if self._embedding_models is None:
            return set()
        try:
            return {
                str(option.get("id") or "")
                for option in self._embedding_models()
                if option.get("id")
            }
        except Exception:
            return set()
