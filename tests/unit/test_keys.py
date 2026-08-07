import pytest

from prodkit_storage.redis.keys import KeyBuilder


def test_key_builder_encodes_segments_and_hashes_long_keys() -> None:
    builder = KeyBuilder("prodkit", max_length=80)
    assert builder.build("tenant 1", "settings") == "prodkit:v1:tenant%201:settings"
    hashed = builder.build("x" * 500)
    assert ":sha256:" in hashed
    assert len(hashed.encode("utf-8")) <= 80

    with pytest.raises(ValueError, match="at least 80"):
        KeyBuilder("prodkit", max_length=79)
