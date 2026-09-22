"""Начальная миграция: таблица реестра документов корпуса.

Единственная миграция проекта. Прежняя цепочка из восьми ревизий удалена
вместе с аккаунтами, сессиями, перепиской и оценками: приложению нужна
только эта таблица. Схема прежних таблиц в уже существующих базах здесь
не создаётся и не удаляется.

Таблица создаётся сразу в полном виде — вместе с идентификатором документа и
двумя его переключателями:

* `document_id` — идентификатор для адресов выдачи оригинала; имя остаётся
  ключом операций загрузки и удаления, а ID не меняется при замене файла;
* `download_allowed` — разрешение выдать оригинал, по умолчанию выключено:
  старый документ нельзя скачать, пока разрешение не включат явно;
* `index_enabled` — участие в поиске, по умолчанию включено: выключенный
  документ не индексируется, поэтому его фрагменты не попадают в ответы, но
  оригинал по-прежнему можно выдать.

Промежуточных ревизий (отдельной для разрешения на скачивание, отдельной для
участия в поиске) в каталоге нет: база собирается заново одной командой
`alembic upgrade head`. Базу, которая уже стояла на одной из прежних ревизий,
помечают начальной, иначе Alembic не сможет разрешить текущее значение:
    alembic stamp --purge 0001_corpus_documents

`--purge` обязателен: прежних ревизий больше нет в каталоге версий, поэтому
обычный stamp не сработает. Столбцы в такой базе уже есть — она создавалась
теми же правилами.

Если данные реестра не нужны, базу проще пересоздать: документы лежат в
`data/docs` и после обновления схемы загружаются заново через страницу
«Документы». Файл, положенный в каталог мимо интерфейса, в корпус не попадает.

Реестр — источник истины о том, что принадлежит базе знаний: индекс
собирается по нему, поэтому документ без записи в реестре в ответы не
попадёт, пока его не загрузят через интерфейс.
"""
from alembic import op

revision = "0001_corpus_documents"
down_revision = None
branch_labels = None
depends_on = None

UNIQUE_NAME = "uq_corpus_documents_document_id"


def upgrade() -> None:
    if op.get_bind().dialect.name == "sqlite":
        op.execute(
            """
            CREATE TABLE corpus_documents (
                name TEXT PRIMARY KEY,
                document_id VARCHAR(36) NOT NULL,
                origin TEXT NOT NULL DEFAULT 'ui',
                uploaded_by TEXT NOT NULL DEFAULT '',
                uploaded_at TEXT NOT NULL,
                size INTEGER NOT NULL DEFAULT 0,
                sha256 TEXT NOT NULL DEFAULT '',
                download_allowed BOOLEAN NOT NULL DEFAULT 0,
                index_enabled BOOLEAN NOT NULL DEFAULT 1,
                CONSTRAINT uq_corpus_documents_document_id UNIQUE (document_id)
            )
            """
        )
        return
    op.execute(
        """
        CREATE TABLE corpus_documents (
            name TEXT PRIMARY KEY,
            document_id VARCHAR(36) NOT NULL,
            origin TEXT NOT NULL DEFAULT 'ui',
            uploaded_by TEXT NOT NULL DEFAULT '',
            uploaded_at TIMESTAMPTZ NOT NULL,
            size BIGINT NOT NULL DEFAULT 0,
            sha256 TEXT NOT NULL DEFAULT '',
            download_allowed BOOLEAN NOT NULL DEFAULT false,
            index_enabled BOOLEAN NOT NULL DEFAULT true,
            CONSTRAINT uq_corpus_documents_document_id UNIQUE (document_id)
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE corpus_documents")
