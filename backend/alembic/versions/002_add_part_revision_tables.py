"""Add Part/Revision/File/Changelog tables for Phase 1 Redesign.

Revision ID: 002
Revises: 001
Create Date: 2026-02-21 10:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '002'
down_revision = '001'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create new part-based revision system tables."""

    # Create enum types for revision phases and statuses
    revision_phase_enum = sa.Enum(
        'rfq_phase', 'engineering', 'freeze', 'ecn',
        name='revisionphase',
        native_enum=False
    )
    revision_phase_enum.create(op.get_bind())

    revision_status_enum = sa.Enum(
        'draft', 'in_progress', 'in_review', 'approved', 'rejected', 'frozen', 'cancelled',
        name='revisionstatus',
        native_enum=False
    )
    revision_status_enum.create(op.get_bind())

    test_data_status_enum = sa.Enum(
        'unconfirmed', 'approved', 'rejected',
        name='testdatastatus',
        native_enum=False
    )
    test_data_status_enum.create(op.get_bind())

    # Create parts table (engineering parts with revisions)
    op.create_table(
        'parts',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('project_id', sa.Integer(), nullable=False),
        sa.Column('part_number', sa.String(100), nullable=False, index=True),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('part_type', sa.String(50), nullable=False),
        sa.Column('supplier', sa.String(255), nullable=True),
        sa.Column('data_classification', sa.String(20), nullable=False),
        sa.Column('active_revision_id', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('created_by', sa.Integer(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.Column('updated_by', sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id']),
        sa.ForeignKeyConstraint(['created_by'], ['users.id']),
        sa.ForeignKeyConstraint(['updated_by'], ['users.id']),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_parts_part_number'), 'parts', ['part_number'])

    # part_revisions table
    op.create_table(
        'part_revisions',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('part_id', sa.Integer(), nullable=False),
        sa.Column('revision_name', sa.String(20), nullable=False, index=True),
        sa.Column('phase', sa.Enum('rfq_phase', 'engineering', 'freeze', 'ecn', name='revisionphase', native_enum=False), nullable=False, index=True),
        sa.Column('status', sa.Enum('draft', 'in_progress', 'in_review', 'approved', 'rejected', 'frozen', 'cancelled', name='revisionstatus', native_enum=False), nullable=False),
        sa.Column('test_data_status', sa.Enum('unconfirmed', 'approved', 'rejected', name='testdatastatus', native_enum=False), nullable=True),
        sa.Column('parent_revision_id', sa.Integer(), nullable=True),
        sa.Column('supersedes_revision_id', sa.Integer(), nullable=True),
        sa.Column('summary', sa.Text(), nullable=True),
        sa.Column('change_reason', sa.Text(), nullable=True),
        sa.Column('impact_analysis', sa.Text(), nullable=True),
        sa.Column('frozen_at', sa.DateTime(), nullable=True),
        sa.Column('frozen_by', sa.Integer(), nullable=True),
        sa.Column('cancelled_at', sa.DateTime(), nullable=True),
        sa.Column('cancelled_by', sa.Integer(), nullable=True),
        sa.Column('cancellation_reason', sa.Text(), nullable=True),
        sa.Column('approved_at', sa.DateTime(), nullable=True),
        sa.Column('approved_by', sa.Integer(), nullable=True),
        sa.Column('approval_notes', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('created_by', sa.Integer(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.Column('updated_by', sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(['part_id'], ['parts.id']),
        sa.ForeignKeyConstraint(['parent_revision_id'], ['part_revisions.id']),
        sa.ForeignKeyConstraint(['supersedes_revision_id'], ['part_revisions.id']),
        sa.ForeignKeyConstraint(['frozen_by'], ['users.id']),
        sa.ForeignKeyConstraint(['cancelled_by'], ['users.id']),
        sa.ForeignKeyConstraint(['approved_by'], ['users.id']),
        sa.ForeignKeyConstraint(['created_by'], ['users.id']),
        sa.ForeignKeyConstraint(['updated_by'], ['users.id']),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_part_revisions_phase'), 'part_revisions', ['phase'])
    op.create_index(op.f('ix_part_revisions_revision_name'), 'part_revisions', ['revision_name'])

    # revision_files table
    op.create_table(
        'revision_files',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('revision_id', sa.Integer(), nullable=False),
        sa.Column('filename', sa.String(255), nullable=False),
        sa.Column('file_type', sa.String(50), nullable=False),
        sa.Column('mime_type', sa.String(100), nullable=False),
        sa.Column('file_size', sa.Integer(), nullable=False),
        sa.Column('file_path', sa.String(500), nullable=False),
        sa.Column('cad_format', sa.String(20), nullable=True),
        sa.Column('cad_data', sa.JSON(), nullable=True),
        sa.Column('file_hash', sa.String(64), nullable=False),
        sa.Column('encrypted', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('encryption_key_ref', sa.String(255), nullable=True),
        sa.Column('viewer_file_path', sa.String(500), nullable=True),
        sa.Column('has_viewer', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('is_deleted', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('deleted_at', sa.DateTime(), nullable=True),
        sa.Column('uploaded_at', sa.DateTime(), nullable=False),
        sa.Column('uploaded_by', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(['revision_id'], ['part_revisions.id']),
        sa.ForeignKeyConstraint(['uploaded_by'], ['users.id']),
        sa.PrimaryKeyConstraint('id')
    )

    # revision_changelogs table
    op.create_table(
        'revision_changelogs',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('part_id', sa.Integer(), nullable=False),
        sa.Column('revision_id', sa.Integer(), nullable=True),
        sa.Column('action', sa.String(50), nullable=False),
        sa.Column('action_description', sa.Text(), nullable=False),
        sa.Column('field_name', sa.String(100), nullable=True),
        sa.Column('old_value', sa.Text(), nullable=True),
        sa.Column('new_value', sa.Text(), nullable=True),
        sa.Column('file_id', sa.Integer(), nullable=True),
        sa.Column('performed_by', sa.Integer(), nullable=False),
        sa.Column('performed_at', sa.DateTime(), nullable=False, index=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('ip_address', sa.String(45), nullable=True),
        sa.Column('previous_hash', sa.String(64), nullable=True),
        sa.Column('entry_hash', sa.String(64), nullable=True),
        sa.ForeignKeyConstraint(['part_id'], ['parts.id']),
        sa.ForeignKeyConstraint(['revision_id'], ['part_revisions.id']),
        sa.ForeignKeyConstraint(['file_id'], ['revision_files.id']),
        sa.ForeignKeyConstraint(['performed_by'], ['users.id']),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_revision_changelogs_performed_at'), 'revision_changelogs', ['performed_at'])

    # Add foreign key constraint for active_revision_id after part_revisions table is created
    with op.batch_alter_table('parts', schema=None) as batch_op:
        batch_op.create_foreign_key(None, 'part_revisions', ['active_revision_id'], ['id'])


def downgrade() -> None:
    """Remove Part/Revision/File/Changelog tables."""

    # Drop tables in reverse order (child tables first, parent last)
    op.drop_table('revision_changelogs')
    op.drop_table('revision_files')
    op.drop_table('part_revisions')
    op.drop_table('parts')

    # Drop enum types
    sa.Enum(name='testdatastatus').drop(op.get_bind())
    sa.Enum(name='revisionstatus').drop(op.get_bind())
    sa.Enum(name='revisionphase').drop(op.get_bind())
