"""Initial experiment schema. Clinical labels belong only to evaluations."""

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint, Uuid, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class ClinicalCase(Base):
    __tablename__ = "clinical_cases"
    __table_args__ = (CheckConstraint("length(trim(anonymous_patient_code)) > 0", name="ck_case_code"),)

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    anonymous_patient_code: Mapped[str] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    images: Mapped[list["Image"]] = relationship(back_populates="case", passive_deletes="all")


class Image(Base):
    __tablename__ = "images"
    __table_args__ = (
        CheckConstraint("width > 0 AND height > 0", name="ck_image_dimensions"),
        CheckConstraint("sha256 ~ '^[0-9a-f]{64}$'", name="ck_image_sha256"),
        CheckConstraint("length(trim(original_filename)) > 0", name="ck_image_filename"),
        CheckConstraint("length(trim(storage_path)) > 0", name="ck_image_path"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    case_id: Mapped[UUID] = mapped_column(ForeignKey("clinical_cases.id", ondelete="RESTRICT"), index=True)
    original_filename: Mapped[str] = mapped_column(Text)
    storage_path: Mapped[str] = mapped_column(Text, unique=True)
    width: Mapped[int] = mapped_column(Integer)
    height: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    case: Mapped[ClinicalCase] = relationship(back_populates="images")
    evaluations: Mapped[list["Evaluation"]] = relationship(back_populates="image", passive_deletes="all")


class Evaluation(Base):
    __tablename__ = "evaluations"
    __table_args__ = (
        CheckConstraint("pci_region_id BETWEEN 0 AND 12", name="ck_evaluation_region"),
        CheckConstraint("clinical_ls BETWEEN 0 AND 3", name="ck_evaluation_ls"),
        CheckConstraint("confidence BETWEEN 0 AND 1", name="ck_evaluation_confidence"),
        CheckConstraint("length(trim(annotator_code)) > 0", name="ck_evaluation_annotator"),
        CheckConstraint("status IN ('draft', 'finalized')", name="ck_evaluation_status"),
        CheckConstraint("(status = 'draft' AND finalized_at IS NULL) OR (status = 'finalized' AND finalized_at IS NOT NULL)", name="ck_evaluation_finalized_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    image_id: Mapped[UUID] = mapped_column(ForeignKey("images.id", ondelete="RESTRICT"), index=True)
    pci_region_id: Mapped[int] = mapped_column(Integer)
    annotator_code: Mapped[str] = mapped_column(String(128))
    clinical_ls: Mapped[int | None] = mapped_column(Integer)
    confidence: Mapped[float | None] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String(16), server_default="draft")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finalized_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    image: Mapped[Image] = relationship(back_populates="evaluations")
    attempts: Mapped[list["SegmentationAttempt"]] = relationship(back_populates="evaluation", order_by="SegmentationAttempt.sequence_number", passive_deletes="all")


class SegmentationAttempt(Base):
    __tablename__ = "segmentation_attempts"
    __table_args__ = (
        UniqueConstraint("evaluation_id", "sequence_number", name="uq_attempt_evaluation_sequence"),
        CheckConstraint("sequence_number > 0", name="ck_attempt_sequence"),
        CheckConstraint("prompt_type IN ('box', 'points')", name="ck_attempt_prompt_type"),
        CheckConstraint("jsonb_typeof(prompt_data) = 'object'", name="ck_attempt_prompt_object"),
        CheckConstraint("jsonb_typeof(sam_metadata) = 'object'", name="ck_attempt_metadata_object"),
        CheckConstraint("length(trim(mask_storage_path)) > 0", name="ck_attempt_mask_path"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    evaluation_id: Mapped[UUID] = mapped_column(ForeignKey("evaluations.id", ondelete="RESTRICT"))
    sequence_number: Mapped[int] = mapped_column(Integer)
    prompt_type: Mapped[str] = mapped_column(String(16))
    prompt_data: Mapped[dict[str, Any]] = mapped_column(JSONB(none_as_null=True))
    mask_storage_path: Mapped[str] = mapped_column(Text, unique=True)
    sam_metadata: Mapped[dict[str, Any]] = mapped_column(JSONB(none_as_null=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    evaluation: Mapped[Evaluation] = relationship(back_populates="attempts")
