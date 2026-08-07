from prodkit_storage.database.locks import advisory_lock_key


def test_advisory_key_is_stable_and_namespaced() -> None:
    assert advisory_lock_key("invoice", "123") == advisory_lock_key("invoice", "123")
    assert advisory_lock_key("invoice", "123") != advisory_lock_key("order", "123")
