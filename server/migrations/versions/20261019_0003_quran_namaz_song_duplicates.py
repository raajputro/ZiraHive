"""Namaz settings and tracker; duplicate-song marks on tracks

Revision ID: 0003
Revises: 0002
Created: 2026-10-19
"""
from alembic import op
import sqlalchemy as sa


revision = '0003'
down_revision = '0002'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('prayer_settings',
    sa.Column('user_id', sa.String(length=32), nullable=False),
    sa.Column('settings', sa.Text(), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('user_id')
    )
    op.create_table('prayer_log',
    sa.Column('id', sa.String(length=32), nullable=False),
    sa.Column('user_id', sa.String(length=32), nullable=False),
    sa.Column('day', sa.String(length=10), nullable=False),
    sa.Column('prayer', sa.String(length=8), nullable=False),
    sa.Column('status', sa.String(length=8), nullable=False),
    sa.Column('jamaah', sa.Boolean(), server_default=sa.false(), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('user_id', 'day', 'prayer')
    )
    op.create_index(op.f('ix_prayer_log_user_id'), 'prayer_log', ['user_id'], unique=False)
    op.create_index(op.f('ix_prayer_log_day'), 'prayer_log', ['day'], unique=False)
    with op.batch_alter_table('tracks') as t:
        t.add_column(sa.Column('duplicate_of', sa.String(length=32), nullable=True))
        t.add_column(sa.Column('dup_moved', sa.Boolean(), server_default=sa.false(), nullable=False))
        t.add_column(sa.Column('dup_kept', sa.Boolean(), server_default=sa.false(), nullable=False))
    op.create_index(op.f('ix_tracks_duplicate_of'), 'tracks', ['duplicate_of'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_tracks_duplicate_of'), table_name='tracks')
    with op.batch_alter_table('tracks') as t:
        t.drop_column('dup_kept')
        t.drop_column('dup_moved')
        t.drop_column('duplicate_of')
    op.drop_index(op.f('ix_prayer_log_day'), table_name='prayer_log')
    op.drop_index(op.f('ix_prayer_log_user_id'), table_name='prayer_log')
    op.drop_table('prayer_log')
    op.drop_table('prayer_settings')
