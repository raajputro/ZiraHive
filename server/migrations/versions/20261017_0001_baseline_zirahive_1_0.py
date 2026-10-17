"""baseline: ZiraHive 1.0

Revision ID: 0001
Revises: (the first one)
Created: 2026-10-17 11:11:54.884165
"""
from alembic import op
import sqlalchemy as sa


revision = '0001'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('backup_config',
    sa.Column('id', sa.String(length=16), nullable=False),
    sa.Column('enabled', sa.Boolean(), nullable=False),
    sa.Column('repository', sa.Text(), nullable=False),
    sa.Column('password', sa.Text(), nullable=False),
    sa.Column('env_json', sa.Text(), nullable=False),
    sa.Column('hour', sa.Integer(), nullable=False),
    sa.Column('include_media', sa.Boolean(), nullable=False),
    sa.Column('keep_daily', sa.Integer(), nullable=False),
    sa.Column('keep_weekly', sa.Integer(), nullable=False),
    sa.Column('keep_monthly', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('backup_runs',
    sa.Column('id', sa.String(length=32), nullable=False),
    sa.Column('kind', sa.String(length=16), nullable=False),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('started_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('snapshot_id', sa.String(length=80), nullable=True),
    sa.Column('files_new', sa.Integer(), nullable=True),
    sa.Column('files_changed', sa.Integer(), nullable=True),
    sa.Column('bytes_added', sa.BigInteger(), nullable=True),
    sa.Column('total_bytes', sa.BigInteger(), nullable=True),
    sa.Column('message', sa.Text(), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('backup_runs', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_backup_runs_started_at'), ['started_at'], unique=False)

    op.create_table('fed_guests',
    sa.Column('id', sa.String(length=32), nullable=False),
    sa.Column('name', sa.String(length=100), nullable=False),
    sa.Column('token_hash', sa.String(length=64), nullable=False),
    sa.Column('library_ids', sa.Text(), nullable=False),
    sa.Column('max_age', sa.Integer(), nullable=True),
    sa.Column('created_by', sa.String(length=64), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('last_seen_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('fed_guests', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_fed_guests_token_hash'), ['token_hash'], unique=True)

    op.create_table('fed_links',
    sa.Column('id', sa.String(length=32), nullable=False),
    sa.Column('name', sa.String(length=100), nullable=False),
    sa.Column('url', sa.String(length=512), nullable=False),
    sa.Column('token', sa.String(length=128), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('last_ok_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('last_error', sa.Text(), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('libraries',
    sa.Column('id', sa.String(length=32), nullable=False),
    sa.Column('name', sa.String(length=128), nullable=False),
    sa.Column('path', sa.Text(), nullable=False),
    sa.Column('kind', sa.String(length=16), nullable=False),
    sa.Column('sort_order', sa.Integer(), server_default='0', nullable=False),
    sa.Column('age_rating', sa.Integer(), nullable=True),
    sa.Column('last_scan_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('path')
    )
    op.create_table('plugin_states',
    sa.Column('id', sa.String(length=40), nullable=False),
    sa.Column('enabled', sa.Boolean(), nullable=False),
    sa.Column('settings_json', sa.Text(), nullable=False),
    sa.Column('last_error', sa.Text(), nullable=True),
    sa.Column('last_error_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('last_ok_at', sa.DateTime(timezone=True), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('users',
    sa.Column('id', sa.String(length=32), nullable=False),
    sa.Column('username', sa.String(length=64), nullable=False),
    sa.Column('password_hash', sa.String(length=255), nullable=False),
    sa.Column('is_admin', sa.Boolean(), nullable=False),
    sa.Column('quota_bytes', sa.BigInteger(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('token_version', sa.Integer(), server_default='0', nullable=False),
    sa.Column('totp_secret', sa.String(length=64), nullable=True),
    sa.Column('totp_enabled', sa.Boolean(), server_default=sa.false(), nullable=False),
    sa.Column('ntfy_url', sa.String(length=512), nullable=True),
    sa.Column('language', sa.String(length=8), nullable=True),
    sa.Column('max_age', sa.Integer(), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_users_username'), ['username'], unique=True)

    op.create_table('assets',
    sa.Column('id', sa.String(length=32), nullable=False),
    sa.Column('owner_id', sa.String(length=32), nullable=False),
    sa.Column('folder', sa.String(length=1024), nullable=False),
    sa.Column('filename', sa.String(length=512), nullable=False),
    sa.Column('size', sa.BigInteger(), nullable=False),
    sa.Column('mime', sa.String(length=128), nullable=False),
    sa.Column('kind', sa.String(length=16), nullable=False),
    sa.Column('sha256', sa.String(length=64), nullable=False),
    sa.Column('storage_path', sa.Text(), nullable=False),
    sa.Column('thumb_ready', sa.Boolean(), nullable=False),
    sa.Column('phash', sa.String(length=16), nullable=True),
    sa.Column('sharpness', sa.Float(), nullable=True),
    sa.Column('ai_indexed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('width', sa.Integer(), nullable=True),
    sa.Column('height', sa.Integer(), nullable=True),
    sa.Column('duration', sa.Float(), nullable=True),
    sa.Column('taken_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('device_asset_id', sa.String(length=255), nullable=True),
    sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['owner_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('assets', schema=None) as batch_op:
        batch_op.create_index('ix_assets_owner_folder', ['owner_id', 'folder'], unique=False)
        batch_op.create_index(batch_op.f('ix_assets_owner_id'), ['owner_id'], unique=False)
        batch_op.create_index('ix_assets_owner_sha', ['owner_id', 'sha256'], unique=False)
        batch_op.create_index('ix_assets_owner_taken', ['owner_id', 'taken_at'], unique=False)
        batch_op.create_index(batch_op.f('ix_assets_phash'), ['phash'], unique=False)

    op.create_table('audit_events',
    sa.Column('id', sa.String(length=32), nullable=False),
    sa.Column('user_id', sa.String(length=32), nullable=True),
    sa.Column('username', sa.String(length=64), nullable=True),
    sa.Column('action', sa.String(length=64), nullable=False),
    sa.Column('detail', sa.Text(), nullable=True),
    sa.Column('ip', sa.String(length=64), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('audit_events', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_audit_events_action'), ['action'], unique=False)
        batch_op.create_index(batch_op.f('ix_audit_events_created_at'), ['created_at'], unique=False)

    op.create_table('books',
    sa.Column('id', sa.String(length=32), nullable=False),
    sa.Column('library_id', sa.String(length=32), nullable=False),
    sa.Column('rel_path', sa.Text(), nullable=False),
    sa.Column('kind', sa.String(length=16), nullable=False),
    sa.Column('format', sa.String(length=16), nullable=False),
    sa.Column('title', sa.String(length=512), nullable=False),
    sa.Column('author', sa.String(length=512), nullable=True),
    sa.Column('narrator', sa.String(length=512), nullable=True),
    sa.Column('series_name', sa.String(length=512), nullable=True),
    sa.Column('series_index', sa.Float(), nullable=True),
    sa.Column('year', sa.Integer(), nullable=True),
    sa.Column('language', sa.String(length=32), nullable=True),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('cover_ready', sa.Boolean(), nullable=False),
    sa.Column('size', sa.BigInteger(), nullable=False),
    sa.Column('mtime', sa.Float(), nullable=False),
    sa.Column('duration', sa.Float(), nullable=True),
    sa.Column('pages', sa.Integer(), nullable=True),
    sa.Column('parts_json', sa.Text(), nullable=True),
    sa.Column('chapters_json', sa.Text(), nullable=True),
    sa.Column('missing', sa.Boolean(), nullable=False),
    sa.Column('added_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['library_id'], ['libraries.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('library_id', 'rel_path')
    )
    with op.batch_alter_table('books', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_books_library_id'), ['library_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_books_series_name'), ['series_name'], unique=False)

    op.create_table('folders',
    sa.Column('id', sa.String(length=32), nullable=False),
    sa.Column('owner_id', sa.String(length=32), nullable=False),
    sa.Column('path', sa.String(length=1024), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['owner_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('owner_id', 'path')
    )
    with op.batch_alter_table('folders', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_folders_owner_id'), ['owner_id'], unique=False)

    op.create_table('music_albums',
    sa.Column('id', sa.String(length=32), nullable=False),
    sa.Column('library_id', sa.String(length=32), nullable=False),
    sa.Column('key', sa.String(length=1024), nullable=False),
    sa.Column('title', sa.String(length=512), nullable=False),
    sa.Column('artist', sa.String(length=512), nullable=False),
    sa.Column('year', sa.Integer(), nullable=True),
    sa.Column('genre', sa.String(length=128), nullable=True),
    sa.Column('cover_ready', sa.Boolean(), nullable=False),
    sa.Column('added_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['library_id'], ['libraries.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('library_id', 'key')
    )
    with op.batch_alter_table('music_albums', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_music_albums_library_id'), ['library_id'], unique=False)

    op.create_table('notifications',
    sa.Column('id', sa.String(length=32), nullable=False),
    sa.Column('user_id', sa.String(length=32), nullable=False),
    sa.Column('kind', sa.String(length=32), nullable=False),
    sa.Column('title', sa.String(length=256), nullable=False),
    sa.Column('body', sa.Text(), nullable=True),
    sa.Column('link', sa.String(length=512), nullable=True),
    sa.Column('read_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('notifications', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_notifications_created_at'), ['created_at'], unique=False)
        batch_op.create_index(batch_op.f('ix_notifications_user_id'), ['user_id'], unique=False)

    op.create_table('passkeys',
    sa.Column('id', sa.String(length=32), nullable=False),
    sa.Column('user_id', sa.String(length=32), nullable=False),
    sa.Column('credential_id', sa.String(length=512), nullable=False),
    sa.Column('public_key', sa.LargeBinary(), nullable=False),
    sa.Column('sign_count', sa.BigInteger(), nullable=False),
    sa.Column('name', sa.String(length=100), nullable=False),
    sa.Column('rp_id', sa.String(length=255), nullable=False),
    sa.Column('transports', sa.String(length=255), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('last_used_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('passkeys', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_passkeys_credential_id'), ['credential_id'], unique=True)
        batch_op.create_index(batch_op.f('ix_passkeys_user_id'), ['user_id'], unique=False)

    op.create_table('people',
    sa.Column('id', sa.String(length=32), nullable=False),
    sa.Column('owner_id', sa.String(length=32), nullable=False),
    sa.Column('name', sa.String(length=100), nullable=True),
    sa.Column('hidden', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['owner_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('people', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_people_owner_id'), ['owner_id'], unique=False)

    op.create_table('playlists',
    sa.Column('id', sa.String(length=32), nullable=False),
    sa.Column('user_id', sa.String(length=32), nullable=False),
    sa.Column('name', sa.String(length=128), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('playlists', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_playlists_user_id'), ['user_id'], unique=False)

    op.create_table('recovery_codes',
    sa.Column('id', sa.String(length=32), nullable=False),
    sa.Column('user_id', sa.String(length=32), nullable=False),
    sa.Column('code_hash', sa.String(length=255), nullable=False),
    sa.Column('used_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('recovery_codes', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_recovery_codes_user_id'), ['user_id'], unique=False)

    op.create_table('remote_progress',
    sa.Column('id', sa.String(length=32), nullable=False),
    sa.Column('user_id', sa.String(length=32), nullable=False),
    sa.Column('link_id', sa.String(length=32), nullable=False),
    sa.Column('media_id', sa.String(length=32), nullable=False),
    sa.Column('title', sa.String(length=512), nullable=False),
    sa.Column('position', sa.Float(), nullable=False),
    sa.Column('duration', sa.Float(), nullable=True),
    sa.Column('finished', sa.Boolean(), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['link_id'], ['fed_links.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('user_id', 'link_id', 'media_id')
    )
    with op.batch_alter_table('remote_progress', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_remote_progress_link_id'), ['link_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_remote_progress_user_id'), ['user_id'], unique=False)

    op.create_table('series',
    sa.Column('id', sa.String(length=32), nullable=False),
    sa.Column('library_id', sa.String(length=32), nullable=False),
    sa.Column('key', sa.String(length=512), nullable=False),
    sa.Column('title', sa.String(length=512), nullable=False),
    sa.Column('year', sa.Integer(), nullable=True),
    sa.Column('overview', sa.Text(), nullable=True),
    sa.Column('poster_ready', sa.Boolean(), server_default=sa.false(), nullable=False),
    sa.Column('tmdb_id', sa.Integer(), nullable=True),
    sa.Column('added_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('certification', sa.String(length=16), nullable=True),
    sa.Column('age_rating', sa.Integer(), nullable=True),
    sa.Column('intro_start', sa.Float(), nullable=True),
    sa.Column('intro_end', sa.Float(), nullable=True),
    sa.Column('credits_before_end', sa.Float(), nullable=True),
    sa.ForeignKeyConstraint(['library_id'], ['libraries.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('library_id', 'key')
    )
    with op.batch_alter_table('series', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_series_library_id'), ['library_id'], unique=False)

    op.create_table('share_links',
    sa.Column('id', sa.String(length=32), nullable=False),
    sa.Column('token', sa.String(length=64), nullable=False),
    sa.Column('owner_id', sa.String(length=32), nullable=False),
    sa.Column('target_type', sa.String(length=16), nullable=False),
    sa.Column('target_id', sa.String(length=1024), nullable=False),
    sa.Column('password_hash', sa.String(length=255), nullable=True),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('allow_download', sa.Boolean(), server_default=sa.true(), nullable=False),
    sa.Column('views', sa.Integer(), server_default='0', nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['owner_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('share_links', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_share_links_owner_id'), ['owner_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_share_links_token'), ['token'], unique=True)

    op.create_table('upload_sessions',
    sa.Column('id', sa.String(length=32), nullable=False),
    sa.Column('owner_id', sa.String(length=32), nullable=False),
    sa.Column('filename', sa.String(length=512), nullable=False),
    sa.Column('folder', sa.String(length=1024), nullable=False),
    sa.Column('size', sa.BigInteger(), nullable=False),
    sa.Column('offset', sa.BigInteger(), nullable=False),
    sa.Column('sha256', sa.String(length=64), nullable=True),
    sa.Column('taken_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('device_asset_id', sa.String(length=255), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('dedupe', sa.Boolean(), server_default=sa.true(), nullable=False),
    sa.Column('replace', sa.Boolean(), server_default=sa.false(), nullable=False),
    sa.ForeignKeyConstraint(['owner_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('upload_sessions', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_upload_sessions_owner_id'), ['owner_id'], unique=False)

    op.create_table('vault_items',
    sa.Column('id', sa.String(length=32), nullable=False),
    sa.Column('user_id', sa.String(length=32), nullable=False),
    sa.Column('size', sa.BigInteger(), nullable=False),
    sa.Column('received', sa.BigInteger(), nullable=False),
    sa.Column('chunk_size', sa.Integer(), nullable=False),
    sa.Column('wrapped_key', sa.Text(), nullable=False),
    sa.Column('meta', sa.Text(), nullable=False),
    sa.Column('has_thumb', sa.Boolean(), nullable=False),
    sa.Column('complete', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('vault_items', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_vault_items_created_at'), ['created_at'], unique=False)
        batch_op.create_index(batch_op.f('ix_vault_items_user_id'), ['user_id'], unique=False)

    op.create_table('vaults',
    sa.Column('id', sa.String(length=32), nullable=False),
    sa.Column('user_id', sa.String(length=32), nullable=False),
    sa.Column('kdf', sa.String(length=32), nullable=False),
    sa.Column('salt', sa.String(length=64), nullable=False),
    sa.Column('iterations', sa.Integer(), nullable=False),
    sa.Column('wrapped_key', sa.Text(), nullable=False),
    sa.Column('recovery_wrapped_key', sa.Text(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('user_id')
    )
    op.create_table('albums',
    sa.Column('id', sa.String(length=32), nullable=False),
    sa.Column('owner_id', sa.String(length=32), nullable=False),
    sa.Column('title', sa.String(length=256), nullable=False),
    sa.Column('cover_asset_id', sa.String(length=32), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['cover_asset_id'], ['assets.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['owner_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('albums', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_albums_owner_id'), ['owner_id'], unique=False)

    op.create_table('asset_texts',
    sa.Column('asset_id', sa.String(length=32), nullable=False),
    sa.Column('text', sa.Text(), nullable=False),
    sa.Column('method', sa.String(length=16), nullable=False),
    sa.Column('pages', sa.Integer(), nullable=True),
    sa.Column('sha256', sa.String(length=64), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['asset_id'], ['assets.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('asset_id')
    )
    op.create_table('asset_versions',
    sa.Column('id', sa.String(length=32), nullable=False),
    sa.Column('asset_id', sa.String(length=32), nullable=False),
    sa.Column('size', sa.BigInteger(), nullable=False),
    sa.Column('sha256', sa.String(length=64), nullable=False),
    sa.Column('storage_path', sa.Text(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['asset_id'], ['assets.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('asset_versions', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_asset_versions_asset_id'), ['asset_id'], unique=False)

    op.create_table('book_progress',
    sa.Column('id', sa.String(length=32), nullable=False),
    sa.Column('user_id', sa.String(length=32), nullable=False),
    sa.Column('book_id', sa.String(length=32), nullable=False),
    sa.Column('position', sa.Float(), nullable=False),
    sa.Column('locator', sa.Text(), nullable=True),
    sa.Column('fraction', sa.Float(), nullable=False),
    sa.Column('finished', sa.Boolean(), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['book_id'], ['books.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('user_id', 'book_id')
    )
    with op.batch_alter_table('book_progress', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_book_progress_book_id'), ['book_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_book_progress_user_id'), ['user_id'], unique=False)

    op.create_table('doc_chunks',
    sa.Column('id', sa.String(length=32), nullable=False),
    sa.Column('asset_id', sa.String(length=32), nullable=False),
    sa.Column('owner_id', sa.String(length=32), nullable=False),
    sa.Column('n', sa.Integer(), nullable=False),
    sa.Column('text', sa.Text(), nullable=False),
    sa.Column('vector', sa.LargeBinary(), nullable=False),
    sa.Column('sha256', sa.String(length=64), nullable=False),
    sa.ForeignKeyConstraint(['asset_id'], ['assets.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['owner_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('doc_chunks', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_doc_chunks_asset_id'), ['asset_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_doc_chunks_owner_id'), ['owner_id'], unique=False)

    op.create_table('faces',
    sa.Column('id', sa.String(length=32), nullable=False),
    sa.Column('asset_id', sa.String(length=32), nullable=False),
    sa.Column('owner_id', sa.String(length=32), nullable=False),
    sa.Column('person_id', sa.String(length=32), nullable=True),
    sa.Column('box', sa.String(length=100), nullable=False),
    sa.Column('score', sa.Float(), nullable=False),
    sa.Column('vector', sa.LargeBinary(), nullable=False),
    sa.Column('confirmed', sa.Boolean(), nullable=False),
    sa.ForeignKeyConstraint(['asset_id'], ['assets.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['owner_id'], ['users.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['person_id'], ['people.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('faces', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_faces_asset_id'), ['asset_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_faces_owner_id'), ['owner_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_faces_person_id'), ['person_id'], unique=False)

    op.create_table('media_items',
    sa.Column('id', sa.String(length=32), nullable=False),
    sa.Column('library_id', sa.String(length=32), nullable=False),
    sa.Column('rel_path', sa.Text(), nullable=False),
    sa.Column('title', sa.String(length=512), nullable=False),
    sa.Column('year', sa.Integer(), nullable=True),
    sa.Column('overview', sa.Text(), nullable=True),
    sa.Column('size', sa.BigInteger(), nullable=False),
    sa.Column('mtime', sa.Float(), nullable=False),
    sa.Column('container', sa.String(length=32), nullable=True),
    sa.Column('video_codec', sa.String(length=32), nullable=True),
    sa.Column('audio_codec', sa.String(length=32), nullable=True),
    sa.Column('width', sa.Integer(), nullable=True),
    sa.Column('height', sa.Integer(), nullable=True),
    sa.Column('duration', sa.Float(), nullable=True),
    sa.Column('poster_ready', sa.Boolean(), nullable=False),
    sa.Column('tmdb_id', sa.Integer(), nullable=True),
    sa.Column('missing', sa.Boolean(), nullable=False),
    sa.Column('added_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('series_id', sa.String(length=32), nullable=True),
    sa.Column('season', sa.Integer(), nullable=True),
    sa.Column('episode', sa.Integer(), nullable=True),
    sa.Column('episode_title', sa.String(length=512), nullable=True),
    sa.Column('tracks_json', sa.Text(), nullable=True),
    sa.Column('intro_start', sa.Float(), nullable=True),
    sa.Column('intro_end', sa.Float(), nullable=True),
    sa.Column('credits_start', sa.Float(), nullable=True),
    sa.Column('certification', sa.String(length=16), nullable=True),
    sa.Column('age_rating', sa.Integer(), nullable=True),
    sa.Column('ai_subtitles', sa.String(length=300), nullable=True),
    sa.ForeignKeyConstraint(['library_id'], ['libraries.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['series_id'], ['series.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('library_id', 'rel_path')
    )
    with op.batch_alter_table('media_items', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_media_items_library_id'), ['library_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_media_items_series_id'), ['series_id'], unique=False)

    op.create_table('photo_vectors',
    sa.Column('asset_id', sa.String(length=32), nullable=False),
    sa.Column('owner_id', sa.String(length=32), nullable=False),
    sa.Column('vector', sa.LargeBinary(), nullable=False),
    sa.ForeignKeyConstraint(['asset_id'], ['assets.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['owner_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('asset_id')
    )
    with op.batch_alter_table('photo_vectors', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_photo_vectors_owner_id'), ['owner_id'], unique=False)

    op.create_table('tracks',
    sa.Column('id', sa.String(length=32), nullable=False),
    sa.Column('library_id', sa.String(length=32), nullable=False),
    sa.Column('album_id', sa.String(length=32), nullable=True),
    sa.Column('rel_path', sa.Text(), nullable=False),
    sa.Column('title', sa.String(length=512), nullable=False),
    sa.Column('artist', sa.String(length=512), nullable=True),
    sa.Column('album_title', sa.String(length=512), nullable=True),
    sa.Column('track_no', sa.Integer(), nullable=True),
    sa.Column('disc_no', sa.Integer(), nullable=True),
    sa.Column('year', sa.Integer(), nullable=True),
    sa.Column('genre', sa.String(length=128), nullable=True),
    sa.Column('duration', sa.Float(), nullable=True),
    sa.Column('codec', sa.String(length=32), nullable=True),
    sa.Column('playable', sa.Boolean(), nullable=False),
    sa.Column('size', sa.BigInteger(), nullable=False),
    sa.Column('mtime', sa.Float(), nullable=False),
    sa.Column('missing', sa.Boolean(), nullable=False),
    sa.Column('added_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['album_id'], ['music_albums.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['library_id'], ['libraries.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('library_id', 'rel_path')
    )
    with op.batch_alter_table('tracks', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_tracks_album_id'), ['album_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_tracks_library_id'), ['library_id'], unique=False)

    op.create_table('album_items',
    sa.Column('id', sa.String(length=32), nullable=False),
    sa.Column('album_id', sa.String(length=32), nullable=False),
    sa.Column('asset_id', sa.String(length=32), nullable=False),
    sa.Column('added_by', sa.String(length=32), nullable=True),
    sa.Column('added_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['added_by'], ['users.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['album_id'], ['albums.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['asset_id'], ['assets.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('album_id', 'asset_id')
    )
    with op.batch_alter_table('album_items', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_album_items_album_id'), ['album_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_album_items_asset_id'), ['asset_id'], unique=False)

    op.create_table('album_members',
    sa.Column('id', sa.String(length=32), nullable=False),
    sa.Column('album_id', sa.String(length=32), nullable=False),
    sa.Column('user_id', sa.String(length=32), nullable=False),
    sa.Column('can_add', sa.Boolean(), server_default=sa.true(), nullable=False),
    sa.ForeignKeyConstraint(['album_id'], ['albums.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('album_id', 'user_id')
    )
    with op.batch_alter_table('album_members', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_album_members_album_id'), ['album_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_album_members_user_id'), ['user_id'], unique=False)

    op.create_table('offline_copies',
    sa.Column('id', sa.String(length=32), nullable=False),
    sa.Column('media_id', sa.String(length=32), nullable=False),
    sa.Column('quality', sa.String(length=8), nullable=False),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('progress', sa.Float(), server_default='0', nullable=False),
    sa.Column('size', sa.BigInteger(), nullable=True),
    sa.Column('error', sa.Text(), nullable=True),
    sa.Column('requested_by', sa.String(length=32), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('last_used_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['media_id'], ['media_items.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['requested_by'], ['users.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('media_id', 'quality')
    )
    with op.batch_alter_table('offline_copies', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_offline_copies_media_id'), ['media_id'], unique=False)

    op.create_table('playlist_tracks',
    sa.Column('id', sa.String(length=32), nullable=False),
    sa.Column('playlist_id', sa.String(length=32), nullable=False),
    sa.Column('track_id', sa.String(length=32), nullable=False),
    sa.Column('position', sa.Integer(), nullable=False),
    sa.ForeignKeyConstraint(['playlist_id'], ['playlists.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['track_id'], ['tracks.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('playlist_tracks', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_playlist_tracks_playlist_id'), ['playlist_id'], unique=False)

    op.create_table('track_stats',
    sa.Column('id', sa.String(length=32), nullable=False),
    sa.Column('user_id', sa.String(length=32), nullable=False),
    sa.Column('track_id', sa.String(length=32), nullable=False),
    sa.Column('favorite', sa.Boolean(), nullable=False),
    sa.Column('plays', sa.Integer(), nullable=False),
    sa.Column('last_played', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['track_id'], ['tracks.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('user_id', 'track_id')
    )
    with op.batch_alter_table('track_stats', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_track_stats_last_played'), ['last_played'], unique=False)
        batch_op.create_index(batch_op.f('ix_track_stats_track_id'), ['track_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_track_stats_user_id'), ['user_id'], unique=False)

    op.create_table('watch_parties',
    sa.Column('id', sa.String(length=32), nullable=False),
    sa.Column('host_id', sa.String(length=32), nullable=False),
    sa.Column('media_id', sa.String(length=32), nullable=False),
    sa.Column('title', sa.String(length=256), nullable=False),
    sa.Column('scheduled_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('control', sa.String(length=16), server_default='everyone', nullable=False),
    sa.Column('wait_for_all', sa.Boolean(), server_default=sa.true(), nullable=False),
    sa.Column('reminded_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('started_notice_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('ended_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('position', sa.Float(), server_default='0', nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['host_id'], ['users.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['media_id'], ['media_items.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('watch_parties', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_watch_parties_host_id'), ['host_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_watch_parties_scheduled_at'), ['scheduled_at'], unique=False)

    op.create_table('watch_progress',
    sa.Column('id', sa.String(length=32), nullable=False),
    sa.Column('user_id', sa.String(length=32), nullable=False),
    sa.Column('media_id', sa.String(length=32), nullable=False),
    sa.Column('position', sa.Float(), nullable=False),
    sa.Column('duration', sa.Float(), nullable=True),
    sa.Column('finished', sa.Boolean(), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['media_id'], ['media_items.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('user_id', 'media_id')
    )
    with op.batch_alter_table('watch_progress', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_watch_progress_user_id'), ['user_id'], unique=False)

    op.create_table('party_members',
    sa.Column('id', sa.String(length=32), nullable=False),
    sa.Column('party_id', sa.String(length=32), nullable=False),
    sa.Column('user_id', sa.String(length=32), nullable=False),
    sa.Column('rsvp', sa.String(length=16), nullable=False),
    sa.ForeignKeyConstraint(['party_id'], ['watch_parties.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('party_id', 'user_id')
    )
    with op.batch_alter_table('party_members', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_party_members_party_id'), ['party_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_party_members_user_id'), ['user_id'], unique=False)

    op.create_table('party_messages',
    sa.Column('id', sa.String(length=32), nullable=False),
    sa.Column('party_id', sa.String(length=32), nullable=False),
    sa.Column('user_id', sa.String(length=32), nullable=True),
    sa.Column('username', sa.String(length=64), nullable=False),
    sa.Column('text', sa.Text(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['party_id'], ['watch_parties.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('party_messages', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_party_messages_created_at'), ['created_at'], unique=False)
        batch_op.create_index(batch_op.f('ix_party_messages_party_id'), ['party_id'], unique=False)



def downgrade() -> None:
    with op.batch_alter_table('party_messages', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_party_messages_party_id'))
        batch_op.drop_index(batch_op.f('ix_party_messages_created_at'))

    op.drop_table('party_messages')
    with op.batch_alter_table('party_members', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_party_members_user_id'))
        batch_op.drop_index(batch_op.f('ix_party_members_party_id'))

    op.drop_table('party_members')
    with op.batch_alter_table('watch_progress', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_watch_progress_user_id'))

    op.drop_table('watch_progress')
    with op.batch_alter_table('watch_parties', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_watch_parties_scheduled_at'))
        batch_op.drop_index(batch_op.f('ix_watch_parties_host_id'))

    op.drop_table('watch_parties')
    with op.batch_alter_table('track_stats', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_track_stats_user_id'))
        batch_op.drop_index(batch_op.f('ix_track_stats_track_id'))
        batch_op.drop_index(batch_op.f('ix_track_stats_last_played'))

    op.drop_table('track_stats')
    with op.batch_alter_table('playlist_tracks', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_playlist_tracks_playlist_id'))

    op.drop_table('playlist_tracks')
    with op.batch_alter_table('offline_copies', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_offline_copies_media_id'))

    op.drop_table('offline_copies')
    with op.batch_alter_table('album_members', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_album_members_user_id'))
        batch_op.drop_index(batch_op.f('ix_album_members_album_id'))

    op.drop_table('album_members')
    with op.batch_alter_table('album_items', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_album_items_asset_id'))
        batch_op.drop_index(batch_op.f('ix_album_items_album_id'))

    op.drop_table('album_items')
    with op.batch_alter_table('tracks', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_tracks_library_id'))
        batch_op.drop_index(batch_op.f('ix_tracks_album_id'))

    op.drop_table('tracks')
    with op.batch_alter_table('photo_vectors', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_photo_vectors_owner_id'))

    op.drop_table('photo_vectors')
    with op.batch_alter_table('media_items', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_media_items_series_id'))
        batch_op.drop_index(batch_op.f('ix_media_items_library_id'))

    op.drop_table('media_items')
    with op.batch_alter_table('faces', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_faces_person_id'))
        batch_op.drop_index(batch_op.f('ix_faces_owner_id'))
        batch_op.drop_index(batch_op.f('ix_faces_asset_id'))

    op.drop_table('faces')
    with op.batch_alter_table('doc_chunks', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_doc_chunks_owner_id'))
        batch_op.drop_index(batch_op.f('ix_doc_chunks_asset_id'))

    op.drop_table('doc_chunks')
    with op.batch_alter_table('book_progress', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_book_progress_user_id'))
        batch_op.drop_index(batch_op.f('ix_book_progress_book_id'))

    op.drop_table('book_progress')
    with op.batch_alter_table('asset_versions', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_asset_versions_asset_id'))

    op.drop_table('asset_versions')
    op.drop_table('asset_texts')
    with op.batch_alter_table('albums', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_albums_owner_id'))

    op.drop_table('albums')
    op.drop_table('vaults')
    with op.batch_alter_table('vault_items', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_vault_items_user_id'))
        batch_op.drop_index(batch_op.f('ix_vault_items_created_at'))

    op.drop_table('vault_items')
    with op.batch_alter_table('upload_sessions', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_upload_sessions_owner_id'))

    op.drop_table('upload_sessions')
    with op.batch_alter_table('share_links', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_share_links_token'))
        batch_op.drop_index(batch_op.f('ix_share_links_owner_id'))

    op.drop_table('share_links')
    with op.batch_alter_table('series', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_series_library_id'))

    op.drop_table('series')
    with op.batch_alter_table('remote_progress', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_remote_progress_user_id'))
        batch_op.drop_index(batch_op.f('ix_remote_progress_link_id'))

    op.drop_table('remote_progress')
    with op.batch_alter_table('recovery_codes', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_recovery_codes_user_id'))

    op.drop_table('recovery_codes')
    with op.batch_alter_table('playlists', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_playlists_user_id'))

    op.drop_table('playlists')
    with op.batch_alter_table('people', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_people_owner_id'))

    op.drop_table('people')
    with op.batch_alter_table('passkeys', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_passkeys_user_id'))
        batch_op.drop_index(batch_op.f('ix_passkeys_credential_id'))

    op.drop_table('passkeys')
    with op.batch_alter_table('notifications', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_notifications_user_id'))
        batch_op.drop_index(batch_op.f('ix_notifications_created_at'))

    op.drop_table('notifications')
    with op.batch_alter_table('music_albums', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_music_albums_library_id'))

    op.drop_table('music_albums')
    with op.batch_alter_table('folders', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_folders_owner_id'))

    op.drop_table('folders')
    with op.batch_alter_table('books', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_books_series_name'))
        batch_op.drop_index(batch_op.f('ix_books_library_id'))

    op.drop_table('books')
    with op.batch_alter_table('audit_events', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_audit_events_created_at'))
        batch_op.drop_index(batch_op.f('ix_audit_events_action'))

    op.drop_table('audit_events')
    with op.batch_alter_table('assets', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_assets_phash'))
        batch_op.drop_index('ix_assets_owner_taken')
        batch_op.drop_index('ix_assets_owner_sha')
        batch_op.drop_index(batch_op.f('ix_assets_owner_id'))
        batch_op.drop_index('ix_assets_owner_folder')

    op.drop_table('assets')
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_users_username'))

    op.drop_table('users')
    op.drop_table('plugin_states')
    op.drop_table('libraries')
    op.drop_table('fed_links')
    with op.batch_alter_table('fed_guests', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_fed_guests_token_hash'))

    op.drop_table('fed_guests')
    with op.batch_alter_table('backup_runs', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_backup_runs_started_at'))

    op.drop_table('backup_runs')
    op.drop_table('backup_config')
