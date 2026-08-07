"""Reusable PostGIS type factories."""

from __future__ import annotations

from geoalchemy2 import Geography, Geometry

WGS84_SRID = 4326
WEB_MERCATOR_SRID = 3857


def point_geometry(*, srid: int = WGS84_SRID, nullable: bool = True) -> Geometry:
    return Geometry(
        geometry_type="POINT",
        srid=srid,
        spatial_index=True,
        nullable=nullable,
    )


def geometry(
    geometry_type: str = "GEOMETRY",
    *,
    srid: int = WGS84_SRID,
    dimension: int = 2,
    nullable: bool = True,
) -> Geometry:
    # GeoAlchemy2 derives dimension from Z/M/ZM suffixes; bare types force 2D.
    resolved_type = _geometry_type_for_dimension(geometry_type, dimension)
    return Geometry(
        geometry_type=resolved_type,
        srid=srid,
        dimension=dimension,
        spatial_index=True,
        nullable=nullable,
    )


def _geometry_type_for_dimension(geometry_type: str, dimension: int) -> str:
    upper = geometry_type.upper()
    if dimension == 4 and not upper.endswith("ZM"):
        base = upper[:-1] if upper.endswith(("Z", "M")) else upper
        return f"{base}ZM"
    if dimension == 3 and not upper.endswith(("Z", "M", "ZM")):
        return f"{upper}Z"
    return geometry_type


def geography(
    geometry_type: str = "GEOMETRY",
    *,
    srid: int = WGS84_SRID,
    nullable: bool = True,
) -> Geography:
    return Geography(
        geometry_type=geometry_type,
        srid=srid,
        spatial_index=True,
        nullable=nullable,
    )
