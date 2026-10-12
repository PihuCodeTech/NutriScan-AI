"""initial schema: users, profiles, scans, scan_items, intake_entries, chat, insight_cache

Revision ID: 0001
Revises:
Create Date: 2026-09-28

scans.logged_intake_id and intake_entries.scan_id reference each other, so the scans → intake_entries
foreign key is added after both tables exist (batch mode so it also works on SQLite).
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("password_hash", sa.String(length=100), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
    )
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_users_email"), ["email"], unique=True)

    op.create_table(
        "insight_cache",
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("totals_hash", sa.String(length=64), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_insight_cache_user_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_insight_cache")),
        sa.UniqueConstraint("user_id", "date", "totals_hash", name="uq_insight_cache_user_date_hash"),
    )
    with op.batch_alter_table("insight_cache", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_insight_cache_user_id"), ["user_id"], unique=False)

    op.create_table(
        "profiles",
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("age", sa.Integer(), nullable=True),
        sa.Column("sex", sa.String(length=10), nullable=True),
        sa.Column("height_cm", sa.Float(), nullable=True),
        sa.Column("weight_kg", sa.Float(), nullable=True),
        sa.Column("activity_level", sa.String(length=20), nullable=True),
        sa.Column("goal", sa.String(length=10), nullable=True),
        sa.Column("diet_type", sa.String(length=15), nullable=True),
        sa.Column("allergies", sa.JSON(), nullable=False),
        sa.Column("conditions", sa.JSON(), nullable=False),
        sa.Column("country", sa.String(length=2), nullable=False),
        sa.Column("timezone", sa.String(length=64), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_profiles_user_id_users"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id", name=op.f("pk_profiles")),
    )
    op.create_table(
        "scans",
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("status", sa.String(length=12), nullable=False),
        sa.Column("image_path", sa.String(length=255), nullable=False),
        sa.Column("image_sha256", sa.String(length=64), nullable=False),
        sa.Column("description", sa.String(length=300), nullable=True),
        sa.Column("meal_type", sa.String(length=12), nullable=False),
        sa.Column("meal_name", sa.String(length=120), nullable=True),
        sa.Column("classifier_model", sa.String(length=200), nullable=True),
        sa.Column("classifier_predictions", sa.JSON(), nullable=True),
        sa.Column("ai_model", sa.String(length=100), nullable=False),
        sa.Column("totals", sa.JSON(), nullable=False),
        sa.Column("health", sa.JSON(), nullable=False),
        sa.Column("raw_ai_response", sa.JSON(), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.Column("logged_intake_id", sa.String(length=36), nullable=True),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_scans_user_id_users"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_scans")),
    )
    with op.batch_alter_table("scans", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_scans_image_sha256"), ["image_sha256"], unique=False)
        batch_op.create_index(batch_op.f("ix_scans_user_id"), ["user_id"], unique=False)

    op.create_table(
        "chat_sessions",
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("title", sa.String(length=120), nullable=False),
        sa.Column("scan_id", sa.String(length=36), nullable=True),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["scan_id"], ["scans.id"], name=op.f("fk_chat_sessions_scan_id_scans"), ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_chat_sessions_user_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_chat_sessions")),
    )
    with op.batch_alter_table("chat_sessions", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_chat_sessions_user_id"), ["user_id"], unique=False)

    op.create_table(
        "intake_entries",
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("source", sa.String(length=12), nullable=False),
        sa.Column("scan_id", sa.String(length=36), nullable=True),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("meal_type", sa.String(length=12), nullable=False),
        sa.Column("eaten_at", sa.DateTime(), nullable=False),
        sa.Column("local_date", sa.Date(), nullable=False),
        sa.Column("items", sa.JSON(), nullable=False),
        sa.Column("totals", sa.JSON(), nullable=False),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["scan_id"], ["scans.id"], name=op.f("fk_intake_entries_scan_id_scans"), ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_intake_entries_user_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_intake_entries")),
    )
    with op.batch_alter_table("intake_entries", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_intake_entries_eaten_at"), ["eaten_at"], unique=False)
        batch_op.create_index(batch_op.f("ix_intake_entries_local_date"), ["local_date"], unique=False)
        batch_op.create_index(batch_op.f("ix_intake_entries_user_id"), ["user_id"], unique=False)

    op.create_table(
        "scan_items",
        sa.Column("scan_id", sa.String(length=36), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("canonical_name", sa.String(length=120), nullable=False),
        sa.Column("quantity_g", sa.Float(), nullable=False),
        sa.Column("serving_description", sa.String(length=200), nullable=True),
        sa.Column("confidence", sa.String(length=10), nullable=False),
        sa.Column("source", sa.String(length=12), nullable=False),
        sa.Column("nutrients", sa.JSON(), nullable=False),
        sa.Column("nutrients_per_100g", sa.JSON(), nullable=False),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.ForeignKeyConstraint(
            ["scan_id"], ["scans.id"], name=op.f("fk_scan_items_scan_id_scans"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_scan_items")),
    )
    with op.batch_alter_table("scan_items", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_scan_items_scan_id"), ["scan_id"], unique=False)

    op.create_table(
        "chat_messages",
        sa.Column("session_id", sa.String(length=36), nullable=False),
        sa.Column("role", sa.String(length=10), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("image_path", sa.String(length=255), nullable=True),
        sa.Column("tool_calls", sa.JSON(), nullable=True),
        sa.Column("ai_model", sa.String(length=100), nullable=True),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["chat_sessions.id"],
            name=op.f("fk_chat_messages_session_id_chat_sessions"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_chat_messages")),
    )
    with op.batch_alter_table("chat_messages", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_chat_messages_session_id"), ["session_id"], unique=False)

    with op.batch_alter_table("scans", schema=None) as batch_op:
        batch_op.create_foreign_key(
            "fk_scans_logged_intake_id_intake_entries",
            "intake_entries",
            ["logged_intake_id"],
            ["id"],
            ondelete="SET NULL",
        )


def downgrade() -> None:
    with op.batch_alter_table("scans", schema=None) as batch_op:
        batch_op.drop_constraint("fk_scans_logged_intake_id_intake_entries", type_="foreignkey")

    with op.batch_alter_table("chat_messages", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_chat_messages_session_id"))

    op.drop_table("chat_messages")
    with op.batch_alter_table("scan_items", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_scan_items_scan_id"))

    op.drop_table("scan_items")
    with op.batch_alter_table("intake_entries", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_intake_entries_user_id"))
        batch_op.drop_index(batch_op.f("ix_intake_entries_local_date"))
        batch_op.drop_index(batch_op.f("ix_intake_entries_eaten_at"))

    op.drop_table("intake_entries")
    with op.batch_alter_table("chat_sessions", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_chat_sessions_user_id"))

    op.drop_table("chat_sessions")
    with op.batch_alter_table("scans", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_scans_user_id"))
        batch_op.drop_index(batch_op.f("ix_scans_image_sha256"))

    op.drop_table("scans")
    op.drop_table("profiles")
    with op.batch_alter_table("insight_cache", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_insight_cache_user_id"))

    op.drop_table("insight_cache")
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_users_email"))

    op.drop_table("users")
