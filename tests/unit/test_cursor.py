import pytest

from prodkit_storage.database.pagination import CursorCodec


def test_cursor_round_trip_and_tamper_detection() -> None:
    codec = CursorCodec(b"x" * 32)
    token = codec.encode("2026-08-06T00:00:00+00:00", "abc")
    assert codec.decode(token) == ("2026-08-06T00:00:00+00:00", "abc")

    index = len(token) // 2
    replacement = "A" if token[index] != "A" else "B"
    with pytest.raises(ValueError):
        codec.decode(token[:index] + replacement + token[index + 1 :])
