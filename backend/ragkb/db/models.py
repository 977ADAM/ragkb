"""Модель реестра корпуса."""
from datetime import datetime
from sqlalchemy import BigInteger, Boolean, DateTime, String, Text, false, func
from sqlalchemy.orm import Mapped, mapped_column
from ragkb.core.database import Base
from ragkb.domain.entities import CorpusDocument


class CorpusDocumentRow(Base):
    """Реестр документов корпуса: индекс собирается только по нему."""

    __tablename__ = "corpus_documents"

    # Путь относительно каталога корпуса: у загруженных через интерфейс это
    # просто имя файла, у принятых из каталога — может быть вложенным.
    name: Mapped[str] = mapped_column(Text, primary_key=True)
    # Идентификатор для маршрутов выдачи оригинала: имя остаётся ключом
    # операций загрузки и удаления, а ID не меняется при замене файла.
    # Длина — каноническая запись UUID, как и в миграции 0002.
    document_id: Mapped[str] = mapped_column(String(36), nullable=False, unique=True)
    origin: Mapped[str] = mapped_column(
        Text, nullable=False, default="ui", server_default="ui"
    )
    uploaded_by: Mapped[str] = mapped_column(
        Text, nullable=False, default="", server_default=""
    )
    uploaded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=func.now()
    )
    size: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default="0"
    )
    sha256: Mapped[str] = mapped_column(
        Text, nullable=False, default="", server_default=""
    )
    # Разрешение на выдачу оригинала. Умолчание задаёт и схема: запись,
    # вставленная мимо приложения, не должна открывать файл.
    download_allowed: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=false()
    )

    def to_domain(self) -> CorpusDocument:
        return CorpusDocument(
            name=self.name,
            document_id=self.document_id,
            origin=self.origin,
            uploaded_by=self.uploaded_by,
            uploaded_at=self.uploaded_at.isoformat() if self.uploaded_at else "",
            size=self.size,
            sha256=self.sha256,
            download_allowed=bool(self.download_allowed),
        )
