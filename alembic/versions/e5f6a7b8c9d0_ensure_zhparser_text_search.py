"""ensure zhparser extension + text-search configuration exist

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-05-29

Idempotent repair: storage/vector.py issues ``to_tsvector('zhparser', ...)`` /
``websearch_to_tsquery('zhparser', :q)``, which fail with "text search
configuration 'zhparser' does not exist" on any database whose 001 ran before
the zhparser extension + configuration were part of that revision. alembic
will not replay an already-applied 001, so a forward migration is the only way
to reconcile such databases. Guards make this a no-op where it already exists.
"""

from __future__ import annotations

from alembic import op

revision = "e5f6a7b8c9d0"
down_revision = "d4e5f6a7b8c9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS zhparser")
    op.execute(
        "DO $$ BEGIN "
        "IF NOT EXISTS (SELECT 1 FROM pg_ts_config WHERE cfgname = 'zhparser') THEN "
        "CREATE TEXT SEARCH CONFIGURATION zhparser (PARSER = zhparser); "
        "ALTER TEXT SEARCH CONFIGURATION zhparser ADD MAPPING FOR "
        "n,v,a,i,e,l,j WITH simple; "
        "END IF; "
        "END $$"
    )


def downgrade() -> None:
    # No-op: the zhparser extension + configuration are owned by revision 001;
    # dropping them here would break that revision's invariant.
    pass
