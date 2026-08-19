from __future__ import annotations

import os

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, text

from prodkit_storage.database.capabilities import (
    inspect_postgresql_capabilities_sync,
    require_postgresql_capabilities,
)
from prodkit_storage.database.indexes import inspect_indexes_sync, require_valid_indexes
from prodkit_storage.database.migration_ops import (
    create_tsvector_gin_index_concurrently,
    create_vector_index_concurrently,
)
from prodkit_storage.database.snapshot import repeatable_read_sync
from prodkit_storage.database.vector import HNSWIndexOptions, VectorDistance

pytestmark = pytest.mark.integration

_TABLE = "storage_ci_postgresql_capabilities"
_GIN_INDEX = "ix_storage_ci_capabilities_body_tsv"
_HNSW_INDEX = "ix_storage_ci_capabilities_embedding_hnsw"


def _vector_url() -> str:
    url = os.getenv("PRODKIT_STORAGE_VECTOR_TEST_DATABASE_URL")
    if not url:
        pytest.skip("PRODKIT_STORAGE_VECTOR_TEST_DATABASE_URL is not configured")
    return url.replace("postgresql://", "postgresql+psycopg://", 1)


def test_pgvector_fts_indexes_capabilities_and_repeatable_snapshot() -> None:
    engine = create_engine(_vector_url())
    try:
        with engine.begin() as connection:
            connection.exec_driver_sql(f"DROP TABLE IF EXISTS {_TABLE}")
            connection.exec_driver_sql(
                f"CREATE TABLE {_TABLE} ("
                "id integer PRIMARY KEY, "
                "body text NOT NULL, "
                "body_tsv tsvector GENERATED ALWAYS AS (to_tsvector('simple', body)) STORED, "
                "embedding vector(3) NOT NULL)"
            )
            connection.execute(
                text(
                    f"INSERT INTO {_TABLE} (id, body, embedding) VALUES "  # noqa: S608
                    "(1, :body1, CAST(:vector1 AS vector)), "
                    "(2, :body2, CAST(:vector2 AS vector))"
                ),
                {
                    "body1": "postgresql full text search",
                    "body2": "vector similarity search",
                    "vector1": "[1,0,0]",
                    "vector2": "[0,1,0]",
                },
            )

        with engine.connect() as connection:
            capabilities = inspect_postgresql_capabilities_sync(connection)
            assert capabilities.server_version_num >= 180000
            assert capabilities.supports_pgvector
            assert capabilities.supports_hnsw
            assert capabilities.supports_ivfflat
            assert capabilities.supports_full_text_search
            require_postgresql_capabilities(
                capabilities,
                extensions=("vector",),
                access_methods=("gin", "hnsw", "ivfflat"),
                text_search_configs=("simple",),
            )

        with engine.connect() as connection:
            context = MigrationContext.configure(connection)
            operations = Operations(context)
            with context.begin_transaction():
                create_tsvector_gin_index_concurrently(
                    operations,
                    _GIN_INDEX,
                    _TABLE,
                    "body_tsv",
                )
                create_vector_index_concurrently(
                    operations,
                    _HNSW_INDEX,
                    _TABLE,
                    "embedding",
                    distance=VectorDistance.COSINE,
                    options=HNSWIndexOptions(m=8, ef_construction=32),
                )

        with repeatable_read_sync(engine) as connection:
            assert connection.scalar(text("SHOW transaction_isolation")) == "repeatable read"
            assert connection.scalar(text("SHOW transaction_read_only")) == "on"
            indexes = inspect_indexes_sync(connection, _TABLE)
            require_valid_indexes(indexes, _GIN_INDEX, _HNSW_INDEX)
            by_name = {index.name: index for index in indexes}
            assert by_name[_GIN_INDEX].access_method == "gin"
            assert by_name[_HNSW_INDEX].access_method == "hnsw"
            assert "vector_cosine_ops" in by_name[_HNSW_INDEX].definition
            assert connection.scalar(
                text(
                    f"SELECT count(*) FROM {_TABLE} "  # noqa: S608
                    "WHERE body_tsv @@ websearch_to_tsquery('simple', :query)"
                ),
                {"query": "postgresql search"},
            ) == 1
            nearest = connection.scalar(
                text(
                    f"SELECT id FROM {_TABLE} "  # noqa: S608
                    "ORDER BY embedding <=> CAST(:query AS vector) LIMIT 1"
                ),
                {"query": "[1,0,0]"},
            )
            assert nearest == 1
    finally:
        with engine.begin() as connection:
            connection.exec_driver_sql(f"DROP TABLE IF EXISTS {_TABLE}")
        engine.dispose()
