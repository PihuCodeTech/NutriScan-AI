"""lock down Supabase's Data API: enable RLS on every table and revoke anon/authenticated access

Supabase exposes the `public` schema over PostgREST to anyone holding the project's public (anon) key. This API
never uses that path: the backend connects as `postgres`, which has BYPASSRLS, so RLS with no policies blocks the
Data API and leaves the backend untouched. Privileges are also revoked from `anon`/`authenticated`, now and for
tables created later. No-op on SQLite and on a plain Postgres without Supabase's roles.

Revision ID: 0002
Revises: 0001
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

def _api_roles(bind) -> list[str]:
    rows = bind.exec_driver_sql("SELECT rolname FROM pg_roles WHERE rolname IN ('anon', 'authenticated')")
    return [r[0] for r in rows]


def _public_tables(bind) -> list[str]:
    rows = bind.exec_driver_sql("SELECT tablename FROM pg_tables WHERE schemaname = 'public' ORDER BY tablename")
    return [r[0] for r in rows]


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    roles = ", ".join(_api_roles(bind))
    for table in _public_tables(bind):
        op.execute(f'ALTER TABLE public."{table}" ENABLE ROW LEVEL SECURITY')
        if roles:
            op.execute(f'REVOKE ALL ON TABLE public."{table}" FROM {roles}')
    if roles:
        op.execute(f"REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM {roles}")
        op.execute(f"ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL ON TABLES FROM {roles}")
        op.execute(f"ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL ON SEQUENCES FROM {roles}")


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    roles = ", ".join(_api_roles(bind))
    for table in _public_tables(bind):
        op.execute(f'ALTER TABLE public."{table}" DISABLE ROW LEVEL SECURITY')
        if roles:
            op.execute(f'GRANT ALL ON TABLE public."{table}" TO {roles}')
    if roles:
        op.execute(f"ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO {roles}")
        op.execute(f"ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON SEQUENCES TO {roles}")
