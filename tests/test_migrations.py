"""The Alembic migration builds exactly the schema the ORM models describe."""

from alembic.config import Config
from sqlalchemy import create_engine, inspect

from alembic import command
from app.db import models  # noqa: F401
from app.db.base import Base


def test_upgrade_matches_models_and_downgrades(tmp_path):
    db = tmp_path / "mig.db"
    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", f"sqlite+aiosqlite:///{db}")
    command.upgrade(cfg, "head")

    insp = inspect(create_engine(f"sqlite:///{db}"))
    tables = set(insp.get_table_names()) - {"alembic_version"}
    assert tables == set(Base.metadata.tables)
    for name, table in Base.metadata.tables.items():
        assert {c["name"] for c in insp.get_columns(name)} == {c.name for c in table.columns}, name
    fks = {fk["referred_table"] for fk in insp.get_foreign_keys("scans")}
    assert fks == {"users", "intake_entries"}

    command.check(cfg)  # raises if autogenerate detects drift between models and migrations
    command.downgrade(cfg, "base")
    assert set(inspect(create_engine(f"sqlite:///{db}")).get_table_names()) <= {"alembic_version"}
