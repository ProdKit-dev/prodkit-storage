"""Low-level pgvector SQLAlchemy types and index metadata."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any, cast

from sqlalchemy.sql.type_api import TypeEngine


class VectorKind(StrEnum):
    VECTOR = "vector"
    HALF_VECTOR = "halfvec"
    SPARSE_VECTOR = "sparsevec"
    BIT = "bit"


class VectorDistance(StrEnum):
    L2 = "l2"
    INNER_PRODUCT = "inner_product"
    COSINE = "cosine"
    L1 = "l1"
    HAMMING = "hamming"
    JACCARD = "jaccard"


class VectorIndexMethod(StrEnum):
    HNSW = "hnsw"
    IVFFLAT = "ivfflat"


@dataclass(frozen=True, slots=True)
class HNSWIndexOptions:
    """Optional HNSW build parameters.

    ``None`` delegates to the pgvector extension default. Values are bounded to
    fail early on obviously invalid migration configuration while leaving final
    validation to the installed extension version.
    """

    m: int | None = None
    ef_construction: int | None = None

    def storage_parameters(self) -> dict[str, int]:
        parameters: dict[str, int] = {}
        if self.m is not None:
            if self.m < 2:
                raise ValueError("HNSW m must be at least 2")
            parameters["m"] = self.m
        if self.ef_construction is not None:
            if self.ef_construction < 4:
                raise ValueError("HNSW ef_construction must be at least 4")
            parameters["ef_construction"] = self.ef_construction
        return parameters


@dataclass(frozen=True, slots=True)
class IVFFlatIndexOptions:
    """IVFFlat build parameters.

    ``lists`` is intentionally explicit because its useful value depends on the
    amount and distribution of data present when the index is built.
    """

    lists: int

    def storage_parameters(self) -> dict[str, int]:
        if self.lists < 1:
            raise ValueError("IVFFlat lists must be at least 1")
        return {"lists": self.lists}


def vector_type(kind: VectorKind | str, dimensions: int) -> TypeEngine[Any]:
    """Return a pgvector SQLAlchemy type without making pgvector mandatory.

    Install ``prodkit-storage[vector]`` before calling this helper.
    """

    normalized_kind = VectorKind(kind)
    if dimensions < 1:
        raise ValueError("vector dimensions must be at least 1")
    try:
        from pgvector.sqlalchemy import BIT, HALFVEC, SPARSEVEC, VECTOR
    except ImportError as error:  # pragma: no cover - exercised in minimal consumer installs.
        raise RuntimeError(
            "pgvector Python support is not installed; install prodkit-storage[vector]"
        ) from error

    factories: dict[VectorKind, Any] = {
        VectorKind.VECTOR: VECTOR,
        VectorKind.HALF_VECTOR: HALFVEC,
        VectorKind.SPARSE_VECTOR: SPARSEVEC,
        VectorKind.BIT: BIT,
    }
    return cast(TypeEngine[Any], factories[normalized_kind](dimensions))


def vector_operator_class(
    kind: VectorKind | str,
    distance: VectorDistance | str,
    *,
    method: VectorIndexMethod | str,
) -> str:
    """Return the pgvector operator class for a supported ANN index combination."""

    key = (VectorIndexMethod(method), VectorKind(kind), VectorDistance(distance))
    try:
        return _VECTOR_OPERATOR_CLASSES[key]
    except KeyError as error:
        raise ValueError(
            "unsupported pgvector index combination: "
            f"method={key[0].value}, kind={key[1].value}, distance={key[2].value}"
        ) from error


def vector_distance_operator(distance: VectorDistance | str) -> str:
    """Return the PostgreSQL operator implementing a pgvector distance."""

    return _DISTANCE_OPERATORS[VectorDistance(distance)]


_VECTOR_OPERATOR_CLASSES: dict[tuple[VectorIndexMethod, VectorKind, VectorDistance], str] = {
    (VectorIndexMethod.HNSW, VectorKind.VECTOR, VectorDistance.L2): "vector_l2_ops",
    (VectorIndexMethod.HNSW, VectorKind.VECTOR, VectorDistance.INNER_PRODUCT): "vector_ip_ops",
    (VectorIndexMethod.HNSW, VectorKind.VECTOR, VectorDistance.COSINE): "vector_cosine_ops",
    (VectorIndexMethod.HNSW, VectorKind.VECTOR, VectorDistance.L1): "vector_l1_ops",
    (VectorIndexMethod.HNSW, VectorKind.HALF_VECTOR, VectorDistance.L2): "halfvec_l2_ops",
    (
        VectorIndexMethod.HNSW,
        VectorKind.HALF_VECTOR,
        VectorDistance.INNER_PRODUCT,
    ): "halfvec_ip_ops",
    (VectorIndexMethod.HNSW, VectorKind.HALF_VECTOR, VectorDistance.COSINE): "halfvec_cosine_ops",
    (VectorIndexMethod.HNSW, VectorKind.HALF_VECTOR, VectorDistance.L1): "halfvec_l1_ops",
    (VectorIndexMethod.HNSW, VectorKind.SPARSE_VECTOR, VectorDistance.L2): "sparsevec_l2_ops",
    (
        VectorIndexMethod.HNSW,
        VectorKind.SPARSE_VECTOR,
        VectorDistance.INNER_PRODUCT,
    ): "sparsevec_ip_ops",
    (
        VectorIndexMethod.HNSW,
        VectorKind.SPARSE_VECTOR,
        VectorDistance.COSINE,
    ): "sparsevec_cosine_ops",
    (VectorIndexMethod.HNSW, VectorKind.SPARSE_VECTOR, VectorDistance.L1): "sparsevec_l1_ops",
    (VectorIndexMethod.HNSW, VectorKind.BIT, VectorDistance.HAMMING): "bit_hamming_ops",
    (VectorIndexMethod.HNSW, VectorKind.BIT, VectorDistance.JACCARD): "bit_jaccard_ops",
    (VectorIndexMethod.IVFFLAT, VectorKind.VECTOR, VectorDistance.L2): "vector_l2_ops",
    (
        VectorIndexMethod.IVFFLAT,
        VectorKind.VECTOR,
        VectorDistance.INNER_PRODUCT,
    ): "vector_ip_ops",
    (VectorIndexMethod.IVFFLAT, VectorKind.VECTOR, VectorDistance.COSINE): "vector_cosine_ops",
    (VectorIndexMethod.IVFFLAT, VectorKind.HALF_VECTOR, VectorDistance.L2): "halfvec_l2_ops",
    (
        VectorIndexMethod.IVFFLAT,
        VectorKind.HALF_VECTOR,
        VectorDistance.INNER_PRODUCT,
    ): "halfvec_ip_ops",
    (
        VectorIndexMethod.IVFFLAT,
        VectorKind.HALF_VECTOR,
        VectorDistance.COSINE,
    ): "halfvec_cosine_ops",
    (VectorIndexMethod.IVFFLAT, VectorKind.BIT, VectorDistance.HAMMING): "bit_hamming_ops",
}

_DISTANCE_OPERATORS = {
    VectorDistance.L2: "<->",
    VectorDistance.INNER_PRODUCT: "<#>",
    VectorDistance.COSINE: "<=>",
    VectorDistance.L1: "<+>",
    VectorDistance.HAMMING: "<~>",
    VectorDistance.JACCARD: "<%>",
}


__all__ = [
    "HNSWIndexOptions",
    "IVFFlatIndexOptions",
    "VectorDistance",
    "VectorIndexMethod",
    "VectorKind",
    "vector_distance_operator",
    "vector_operator_class",
    "vector_type",
]
