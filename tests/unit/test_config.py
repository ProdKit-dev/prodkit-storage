from pydantic import SecretStr

from prodkit_storage.config import StorageSettings


def test_plain_postgres_url_gets_correct_drivers() -> None:
    settings = StorageSettings(
        database_url=SecretStr("postgresql://user:password@db:5432/app"),
        cursor_signing_secret=SecretStr("x" * 32),
    )
    assert settings.sync_url.drivername == "postgresql+psycopg"
    assert settings.async_url.drivername == "postgresql+asyncpg"


def test_read_replica_is_optional() -> None:
    settings = StorageSettings(cursor_signing_secret=SecretStr("x" * 32))
    assert settings.sync_read_url is None
    assert settings.async_read_url is None


def test_alembic_model_modules_are_normalized() -> None:
    settings = StorageSettings(
        alembic_model_modules=" myapp.models, myapp.billing.models,myapp.models ",
        cursor_signing_secret=SecretStr("x" * 32),
    )
    assert settings.alembic_model_module_names == (
        "myapp.models",
        "myapp.billing.models",
    )
