from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from prodkit_storage.database.rls_verification import verify_rls_sync
from prodkit_storage.outbox import get_outbox_metrics


class MappingRows:
    def __init__(self, one: Any = None, rows: list[Any] | None = None) -> None:
        self.one = one
        self.rows = rows or []

    def mappings(self) -> MappingRows:
        return self

    def one_or_none(self) -> Any:
        return self.one

    def all(self) -> list[Any]:
        return self.rows


class RLSFakeSession:
    def __init__(self) -> None:
        self.calls = 0

    def execute(self, statement: Any, parameters: Any) -> MappingRows:
        del statement, parameters
        self.calls += 1
        if self.calls == 1:
            return MappingRows(
                one={"rolname": "app_runtime", "rolsuper": False, "rolbypassrls": False}
            )
        return MappingRows(
            rows=[
                {
                    "table_name": "customers",
                    "owner_name": "app_owner",
                    "rls_enabled": True,
                    "force_rls": True,
                    "policy_count": 2,
                }
            ]
        )


class OutboxResult:
    def all(self) -> list[tuple[str, int]]:
        return [("pending", 4), ("processing", 1), ("dead", 2)]


class OutboxFakeSession:
    info: dict[str, Any] = {}

    def execute(self, statement: Any) -> OutboxResult:
        del statement
        return OutboxResult()

    def scalar(self, statement: Any) -> datetime:
        del statement
        return datetime.now(timezone.utc) - timedelta(seconds=30)


def test_rls_verification_detects_safe_runtime_role() -> None:
    report = verify_rls_sync(
        RLSFakeSession(),  # type: ignore[arg-type]
        runtime_role="app_runtime",
        tables=["customers"],
        require_force_rls=True,
    )
    assert report.healthy
    assert not report.issues


def test_outbox_metrics_snapshot() -> None:
    metrics = get_outbox_metrics(OutboxFakeSession())  # type: ignore[arg-type]
    assert metrics.pending == 4
    assert metrics.processing == 1
    assert metrics.dead == 2
    assert metrics.oldest_pending_age_seconds is not None
    assert metrics.oldest_pending_age_seconds >= 29
