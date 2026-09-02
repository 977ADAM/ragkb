from ragkb.domain.ports import ModelCatalog
from ragkb.services.models_schemas import ModelInfo


class ModelsService:
    def __init__(self, catalog: ModelCatalog):
        self.catalog = catalog

    def list(self) -> list[ModelInfo]:
        return self.catalog.list()
