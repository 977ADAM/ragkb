from ragkb.domain.ports import ModelCatalog
from ragkb.services.models_schemas import ModelInfo


class ModelsService:
    def __init__(self, catalog: ModelCatalog):
        self.catalog = catalog

    def list(self) -> list[ModelInfo]:
        return [
            ModelInfo(
                id=item.id,
                display_name=item.display_name,
                context_window=item.context_window,
                supports_tools=item.supports_tools,
                is_default=item.is_default,
            )
            for item in self.catalog.list()
        ]
