"""Recitations are kept apart from songs: tracks.quran

Revision ID: 0004
Revises: 0003
Created: 2026-10-19
"""
from alembic import op
import sqlalchemy as sa


revision = '0004'
down_revision = '0003'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('tracks') as t:
        t.add_column(sa.Column('quran', sa.Boolean(), server_default=sa.false(), nullable=False))
    # files already in Quran categories; Quran folders inside music categories are marked by the next scan
    op.execute("UPDATE tracks SET quran = :yes WHERE library_id IN (SELECT id FROM libraries WHERE kind = 'quran')"
               .replace(":yes", "TRUE" if op.get_bind().dialect.name == "postgresql" else "1"))


def downgrade() -> None:
    with op.batch_alter_table('tracks') as t:
        t.drop_column('quran')
