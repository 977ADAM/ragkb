from ragkb.features.models.ports import ModelCatalog
from ragkb.features.models.schemas import ModelInfo


class ModelsService:
    def __init__(self, catalog: ModelCatalog):
        self.catalog = catalog

    def list(self) -> list[ModelInfo]:
        return self.catalog.list()
