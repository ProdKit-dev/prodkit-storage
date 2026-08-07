from typing import Any

from sqlalchemy import select

from prodkit_storage.database.repository import SyncRepository
from prodkit_storage.models import OutboxEvent


class ScalarResult:
    def all(self) -> list[OutboxEvent]:
        return []


class FakeSession:
    def __init__(self) -> None:
        self.last_statement: Any = None

    def scalars(self, statement: Any) -> ScalarResult:
        self.last_statement = statement
        return ScalarResult()

    def scalar(self, statement: Any) -> int:
        self.last_statement = statement
        return 0


def test_repository_accepts_explicit_select_without_boolean_coercion() -> None:
    session = FakeSession()
    repository = SyncRepository(session, OutboxEvent)  # type: ignore[arg-type]
    statement = select(OutboxEvent).where(OutboxEvent.status == "pending")

    assert repository.list(statement) == []
    assert repository.count(statement) == 0
