"""Initial experiment persistence schema (PostgreSQL)."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0001_experiment"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('clinical_cases',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('anonymous_patient_code', sa.String(length=128), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('length(trim(anonymous_patient_code)) > 0', name='ck_case_code'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('images',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('case_id', sa.Uuid(), nullable=False),
    sa.Column('storage_path', sa.Text(), nullable=False),
    sa.Column('width', sa.Integer(), nullable=False),
    sa.Column('height', sa.Integer(), nullable=False),
    sa.Column('sha256', sa.String(length=64), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("sha256 ~ '^[0-9a-f]{64}$'", name='ck_image_sha256'),
    sa.CheckConstraint('length(trim(storage_path)) > 0', name='ck_image_path'),
    sa.CheckConstraint('width > 0 AND height > 0', name='ck_image_dimensions'),
    sa.ForeignKeyConstraint(['case_id'], ['clinical_cases.id'], ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('storage_path')
    )
    op.create_index(op.f('ix_images_case_id'), 'images', ['case_id'], unique=False)
    op.create_index(op.f('ix_images_sha256'), 'images', ['sha256'], unique=False)
    op.create_table('evaluations',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('image_id', sa.Uuid(), nullable=False),
    sa.Column('pci_region_id', sa.Integer(), nullable=False),
    sa.Column('annotator_code', sa.String(length=128), nullable=False),
    sa.Column('clinical_ls', sa.Integer(), nullable=True),
    sa.Column('annotator_confidence', sa.Float(), nullable=True),
    sa.Column('status', sa.String(length=16), server_default='draft', nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('finalized_at', sa.DateTime(timezone=True), nullable=True),
    sa.CheckConstraint("(status = 'draft' AND finalized_at IS NULL) OR (status = 'finalized' AND finalized_at IS NOT NULL)", name='ck_evaluation_finalized_at'),
    sa.CheckConstraint("status IN ('draft', 'finalized')", name='ck_evaluation_status'),
    sa.CheckConstraint('clinical_ls BETWEEN 0 AND 3', name='ck_evaluation_ls'),
    sa.CheckConstraint("status != 'finalized' OR clinical_ls IS NOT NULL", name='ck_evaluation_finalized_ls'),
    sa.CheckConstraint('annotator_confidence BETWEEN 0 AND 1', name='ck_evaluation_annotator_confidence'),
    sa.CheckConstraint('length(trim(annotator_code)) > 0', name='ck_evaluation_annotator'),
    sa.CheckConstraint('pci_region_id BETWEEN 0 AND 12', name='ck_evaluation_region'),
    sa.ForeignKeyConstraint(['image_id'], ['images.id'], ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_evaluations_image_id'), 'evaluations', ['image_id'], unique=False)
    op.create_table('segmentation_attempts',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('evaluation_id', sa.Uuid(), nullable=False),
    sa.Column('sequence_number', sa.Integer(), nullable=False),
    sa.Column('prompt_type', sa.String(length=16), nullable=False),
    sa.Column('prompt_data', postgresql.JSONB(none_as_null=True, astext_type=sa.Text()), nullable=False),
    sa.Column('mask_storage_path', sa.Text(), nullable=False),
    sa.Column('sam_metadata', postgresql.JSONB(none_as_null=True, astext_type=sa.Text()), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("jsonb_typeof(prompt_data) = 'object'", name='ck_attempt_prompt_object'),
    sa.CheckConstraint("jsonb_typeof(sam_metadata) = 'object'", name='ck_attempt_metadata_object'),
    sa.CheckConstraint("prompt_type IN ('box', 'points')", name='ck_attempt_prompt_type'),
    sa.CheckConstraint('length(trim(mask_storage_path)) > 0', name='ck_attempt_mask_path'),
    sa.CheckConstraint('sequence_number > 0', name='ck_attempt_sequence'),
    sa.ForeignKeyConstraint(['evaluation_id'], ['evaluations.id'], ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('evaluation_id', 'sequence_number', name='uq_attempt_evaluation_sequence'),
    sa.UniqueConstraint('mask_storage_path')
    )


def downgrade():
    op.drop_table('segmentation_attempts')
    op.drop_table('evaluations')
    op.drop_table('images')
    op.drop_table('clinical_cases')

