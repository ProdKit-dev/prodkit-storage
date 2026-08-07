from prodkit_storage.database.base import Base
from prodkit_storage.models import AuditEvent, OutboxEvent


def test_bundled_models_are_registered() -> None:
    assert AuditEvent.__tablename__ == "storage_audit_events"
    assert OutboxEvent.__tablename__ == "storage_outbox_events"
    assert "storage_audit_events" in Base.metadata.tables
    assert "storage_outbox_events" in Base.metadata.tables
