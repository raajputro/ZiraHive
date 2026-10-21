"""IPTV: subscriptions and favourites

Revision ID: 0002
Revises: 0001
Created: 2026-10-18
"""
from alembic import op
import sqlalchemy as sa


revision = '0002'
down_revision = '0001'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('iptv_sources',
    sa.Column('id', sa.String(length=32), nullable=False),
    sa.Column('owner_id', sa.String(length=32), nullable=False),
    sa.Column('name', sa.String(length=80), nullable=False),
    sa.Column('server', sa.String(length=512), nullable=False),
    sa.Column('username', sa.String(length=255), nullable=False),
    sa.Column('password', sa.Text(), nullable=False),
    sa.Column('shared', sa.Boolean(), server_default=sa.false(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['owner_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_iptv_sources_owner_id'), 'iptv_sources', ['owner_id'], unique=False)
    op.create_table('iptv_favorites',
    sa.Column('id', sa.String(length=32), nullable=False),
    sa.Column('user_id', sa.String(length=32), nullable=False),
    sa.Column('source_id', sa.String(length=32), nullable=False),
    sa.Column('kind', sa.String(length=8), nullable=False),
    sa.Column('stream_id', sa.String(length=32), nullable=False),
    sa.Column('name', sa.String(length=255), nullable=False),
    sa.Column('icon', sa.Text(), nullable=True),
    sa.Column('ext', sa.String(length=8), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['source_id'], ['iptv_sources.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('user_id', 'source_id', 'kind', 'stream_id')
    )
    op.create_index(op.f('ix_iptv_favorites_source_id'), 'iptv_favorites', ['source_id'], unique=False)
    op.create_index(op.f('ix_iptv_favorites_user_id'), 'iptv_favorites', ['user_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_iptv_favorites_user_id'), table_name='iptv_favorites')
    op.drop_index(op.f('ix_iptv_favorites_source_id'), table_name='iptv_favorites')
    op.drop_table('iptv_favorites')
    op.drop_index(op.f('ix_iptv_sources_owner_id'), table_name='iptv_sources')
    op.drop_table('iptv_sources')
