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
    return Geometry(
        geometry_type=geometry_type,
        srid=srid,
        dimension=dimension,
        spatial_index=True,
        nullable=nullable,
    )


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
