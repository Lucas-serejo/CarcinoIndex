"""Record specialist review without invalidating legacy finalized evaluations."""
from alembic import op
import sqlalchemy as sa

revision = "0002_segmentation_review"
down_revision = "0001_experiment"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("evaluations", sa.Column("reviewed_attempt_id", sa.Uuid(), nullable=True))
    op.add_column("evaluations", sa.Column("segmentation_quality", sa.String(32), nullable=True))
    op.create_check_constraint("ck_evaluation_segmentation_quality", "evaluations",
                               "segmentation_quality IN ('adequate', 'partially_adequate', 'inadequate')")
    op.create_check_constraint("ck_evaluation_segmentation_review_pair", "evaluations",
                               "(reviewed_attempt_id IS NULL) = (segmentation_quality IS NULL)")


def downgrade():
    op.drop_constraint("ck_evaluation_segmentation_review_pair", "evaluations", type_="check")
    op.drop_constraint("ck_evaluation_segmentation_quality", "evaluations", type_="check")
    op.drop_column("evaluations", "segmentation_quality")
    op.drop_column("evaluations", "reviewed_attempt_id")
