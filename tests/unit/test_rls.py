import pytest

from prodkit_storage.alembic.rls import _identifier, _policy_name


def test_rls_identifiers_are_bounded_and_policy_names_are_stable() -> None:
    assert _identifier("tenant_records") == "tenant_records"
    with pytest.raises(ValueError):
        _identifier("x" * 64)

    table = "x" * 63
    policy = _policy_name(table)
    assert len(policy) <= 63
    assert policy == _policy_name(table)


class FakeOperations:
    def __init__(self) -> None:
        self.statements: list[str] = []

    def execute(self, statement: str) -> None:
        self.statements.append(statement)


def test_enable_and_disable_rls_with_schema() -> None:
    from prodkit_storage.alembic.rls import disable_tenant_rls, enable_tenant_rls

    operations = FakeOperations()
    enable_tenant_rls(operations, "customers", schema="app")  # type: ignore[arg-type]
    assert operations.statements[0] == (
        'ALTER TABLE "app"."customers" ENABLE ROW LEVEL SECURITY'
    )
    assert "FORCE ROW LEVEL SECURITY" in operations.statements[1]
    assert "CREATE POLICY" in operations.statements[2]
    assert "current_setting('app.tenant_id', true)" in operations.statements[2]

    disable_tenant_rls(operations, "customers", schema="app")  # type: ignore[arg-type]
    assert 'DROP POLICY IF EXISTS "customers_tenant_isolation"' in operations.statements[3]
    assert operations.statements[4].endswith("DISABLE ROW LEVEL SECURITY")


def test_rls_rejects_unsafe_setting_and_can_skip_force() -> None:
    from prodkit_storage.alembic.rls import enable_tenant_rls

    operations = FakeOperations()
    with pytest.raises(ValueError, match="unsafe PostgreSQL setting"):
        enable_tenant_rls(  # type: ignore[arg-type]
            operations, "customers", setting="unsafe setting"
        )
    enable_tenant_rls(operations, "customers", force=False)  # type: ignore[arg-type]
    assert len(operations.statements) == 2
