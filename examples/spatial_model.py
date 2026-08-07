from __future__ import annotations

from geoalchemy2.elements import WKBElement
from sqlalchemy import String, select
from sqlalchemy.orm import Mapped, mapped_column

from prodkit_storage.database import Base, TenantMixin, TimestampMixin, UUIDPrimaryKeyMixin
from prodkit_storage.spatial import distance_meters, point_geometry, within_distance


class Place(UUIDPrimaryKeyMixin, TenantMixin, TimestampMixin, Base):
    __tablename__ = "places"

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    location: Mapped[WKBElement] = mapped_column(point_geometry(nullable=False))


def nearby_places(longitude: float, latitude: float, radius_meters: float):
    return (
        select(Place, distance_meters(Place.location, longitude, latitude).label("distance_m"))
        .where(within_distance(Place.location, longitude, latitude, radius_meters))
        .order_by("distance_m")
    )
