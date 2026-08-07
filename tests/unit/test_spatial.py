import pytest

from prodkit_storage.spatial import validate_longitude_latitude


def test_coordinate_validation() -> None:
    validate_longitude_latitude(29.0, 41.0)
    with pytest.raises(ValueError):
        validate_longitude_latitude(181, 0)
    with pytest.raises(ValueError):
        validate_longitude_latitude(0, -91)
