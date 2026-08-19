from __future__ import annotations

import pytest
from sqlalchemy import JSON, column, literal
from sqlalchemy.dialects import postgresql

from prodkit_storage.database.capabilities import (
    DatabaseCapabilityError,
    ExtensionCapability,
    PostgreSQLCapabilities,
    require_postgresql_capabilities,
)
from prodkit_storage.database.full_text import (
    TextQueryParser,
    text_search_match,
    to_tsquery_expression,
    to_tsvector_expression,
)
from prodkit_storage.database.indexes import PostgreSQLIndexState, require_valid_indexes
from prodkit_storage.database.jsonb import jsonb_array_or_scalar, jsonb_text_path
from prodkit_storage.database.vector import (
    HNSWIndexOptions,
    IVFFlatIndexOptions,
    VectorDistance,
    VectorIndexMethod,
    VectorKind,
    vector_distance_operator,
    vector_operator_class,
    vector_type,
)


def _capabilities() -> PostgreSQLCapabilities:
    return PostgreSQLCapabilities(
        server_version="18.0",
        server_version_num=180000,
        extensions=(
            ExtensionCapability("postgis", "3.6", "3.6"),
            ExtensionCapability("vector", "0.8.6", "0.8.6"),
        ),
        access_methods=("btree", "gin", "hnsw", "ivfflat"),
        text_search_configs=("english", "simple"),
    )


def test_capability_snapshot_and_requirements() -> None:
    capabilities = _capabilities()
    assert capabilities.supports_pgvector
    assert capabilities.supports_hnsw
    assert capabilities.supports_ivfflat
    assert capabilities.supports_full_text_search
    assert capabilities.pgvector_version == "0.8.6"
    require_postgresql_capabilities(
        capabilities,
        extensions=("vector",),
        access_methods=("gin", "hnsw"),
        text_search_configs=("english",),
    )
    with pytest.raises(DatabaseCapabilityError, match="extensions=pgcrypto"):
        require_postgresql_capabilities(capabilities, extensions=("pgcrypto",))
    with pytest.raises(ValueError, match="extension name"):
        capabilities.has_extension("bad-name")


def test_vector_operator_classes_and_options_fail_closed() -> None:
    assert (
        vector_operator_class(
            VectorKind.VECTOR,
            VectorDistance.COSINE,
            method=VectorIndexMethod.HNSW,
        )
        == "vector_cosine_ops"
    )
    assert vector_distance_operator(VectorDistance.COSINE) == "<=>"
    assert HNSWIndexOptions(m=16, ef_construction=64).storage_parameters() == {
        "m": 16,
        "ef_construction": 64,
    }
    assert IVFFlatIndexOptions(lists=100).storage_parameters() == {"lists": 100}
    with pytest.raises(ValueError, match="unsupported pgvector"):
        vector_operator_class(
            VectorKind.SPARSE_VECTOR,
            VectorDistance.COSINE,
            method=VectorIndexMethod.IVFFLAT,
        )
    with pytest.raises(ValueError, match="at least 2"):
        HNSWIndexOptions(m=1).storage_parameters()
    with pytest.raises(ValueError, match="at least 1"):
        IVFFlatIndexOptions(lists=0).storage_parameters()


def test_vector_type_compiles_through_optional_pgvector_integration() -> None:
    compiled = vector_type(VectorKind.VECTOR, 3).compile(dialect=postgresql.dialect())
    assert str(compiled) == "VECTOR(3)"


def test_full_text_and_jsonb_expressions_compile_without_raw_query_interpolation() -> None:
    document = column("body")
    query = literal("production search")
    vector = to_tsvector_expression(document, config="english")
    parsed = to_tsquery_expression(query, config="english", parser=TextQueryParser.WEBSEARCH)
    match = text_search_match(vector, parsed)
    sql = str(match.compile(dialect=postgresql.dialect()))
    assert "to_tsvector" in sql
    assert "websearch_to_tsquery" in sql
    assert "@@" in sql

    payload = column("payload", JSON)
    path_expression = jsonb_text_path(payload, "profile", "name")
    path_sql = str(path_expression.compile(dialect=postgresql.dialect()))
    array_sql = str(jsonb_array_or_scalar(payload).compile(dialect=postgresql.dialect()))
    assert "jsonb_extract_path_text" in path_sql
    assert "jsonb_typeof" in array_sql
    assert "jsonb_build_array" in array_sql


def test_required_index_state_rejects_missing_or_invalid_indexes() -> None:
    valid = PostgreSQLIndexState(
        schema="public",
        table="documents",
        name="ix_documents_body",
        access_method="gin",
        unique=False,
        valid=True,
        ready=True,
        predicate=None,
        definition="CREATE INDEX ix_documents_body ON public.documents USING gin (body)",
    )
    require_valid_indexes((valid,), valid.name)
    with pytest.raises(RuntimeError, match="missing=ix_missing"):
        require_valid_indexes((valid,), "ix_missing")
    invalid = PostgreSQLIndexState(
        schema="public",
        table="documents",
        name="ix_invalid",
        access_method="hnsw",
        unique=False,
        valid=False,
        ready=True,
        predicate=None,
        definition="CREATE INDEX ix_invalid ON public.documents USING hnsw (embedding)",
    )
    with pytest.raises(RuntimeError, match="unusable=ix_invalid"):
        require_valid_indexes((invalid,), "ix_invalid")
