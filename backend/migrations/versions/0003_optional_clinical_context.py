"""Allow undetermined specialist-provided region and clinical LS."""
from alembic import op
import sqlalchemy as sa

revision = "0003_optional_clinical_context"
down_revision = "0002_segmentation_review"
branch_labels = None
depends_on = None


def upgrade():
    op.alter_column("evaluations", "pci_region_id", existing_type=sa.Integer(), nullable=True)
    op.drop_constraint("ck_evaluation_finalized_ls", "evaluations", type_="check")
    op.create_check_constraint("ck_evaluation_confidence_requires_ls", "evaluations",
                               "clinical_ls IS NOT NULL OR annotator_confidence IS NULL")


def downgrade():
    # Rows using the new null semantics must be removed before restoring the old contract.
    op.drop_constraint("ck_evaluation_confidence_requires_ls", "evaluations", type_="check")
    op.create_check_constraint("ck_evaluation_finalized_ls", "evaluations",
                               "status != 'finalized' OR clinical_ls IS NOT NULL")
    op.alter_column("evaluations", "pci_region_id", existing_type=sa.Integer(), nullable=False)
