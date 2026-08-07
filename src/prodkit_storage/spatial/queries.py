"""Composable PostGIS SQLAlchemy expressions."""

from __future__ import annotations

from typing import Any

from geoalchemy2 import Geography
from sqlalchemy import cast, func
from sqlalchemy.sql.elements import ColumnElement

from prodkit_storage.spatial.types import WGS84_SRID


def validate_longitude_latitude(longitude: float, latitude: float) -> None:
    if not -180 <= longitude <= 180:
        raise ValueError("longitude must be between -180 and 180")
    if not -90 <= latitude <= 90:
        raise ValueError("latitude must be between -90 and 90")


def make_point(longitude: float, latitude: float, *, srid: int = WGS84_SRID) -> Any:
    validate_longitude_latitude(longitude, latitude)
    return func.ST_SetSRID(func.ST_MakePoint(longitude, latitude), srid)


def distance_meters(
    column: ColumnElement[Any],
    longitude: float,
    latitude: float,
) -> ColumnElement[float]:
    point = make_point(longitude, latitude)
    geography_type = Geography(geometry_type="POINT", srid=WGS84_SRID)
    return func.ST_Distance(cast(column, geography_type), cast(point, geography_type))


def within_distance(
    column: ColumnElement[Any],
    longitude: float,
    latitude: float,
    radius_meters: float,
) -> ColumnElement[bool]:
    if radius_meters < 0:
        raise ValueError("radius_meters cannot be negative")
    point = make_point(longitude, latitude)
    geography_type = Geography(geometry_type="POINT", srid=WGS84_SRID)
    return func.ST_DWithin(
        cast(column, geography_type),
        cast(point, geography_type),
        radius_meters,
    )


def intersects(column: ColumnElement[Any], geometry_value: Any) -> ColumnElement[bool]:
    return func.ST_Intersects(column, geometry_value)


def contains(column: ColumnElement[Any], geometry_value: Any) -> ColumnElement[bool]:
    return func.ST_Contains(column, geometry_value)


def bounding_box(
    min_longitude: float,
    min_latitude: float,
    max_longitude: float,
    max_latitude: float,
    *,
    srid: int = WGS84_SRID,
) -> Any:
    validate_longitude_latitude(min_longitude, min_latitude)
    validate_longitude_latitude(max_longitude, max_latitude)
    if min_longitude >= max_longitude or min_latitude >= max_latitude:
        raise ValueError("bounding box minimums must be lower than maximums")
    return func.ST_MakeEnvelope(
        min_longitude,
        min_latitude,
        max_longitude,
        max_latitude,
        srid,
    )
