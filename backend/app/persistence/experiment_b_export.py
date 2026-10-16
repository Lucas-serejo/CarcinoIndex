"""Read-only CSV export of finalized Experiment B evaluations.

One row per finalized Evaluation. Technical metadata comes only from the
SegmentationAttempt referenced by ``reviewed_attempt_id``. No image, mask,
storage path, or SAM model is opened; the database transaction is READ ONLY.
"""

import csv
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy import func, select, text
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.orm import aliased

from .models import ClinicalCase, Evaluation, Image, SegmentationAttempt

COLUMNS = (
    "evaluation_id", "case_id", "case_code", "image_id", "image_sha256",
    "image_width", "image_height", "annotator_code", "pci_region_id",
    "segmentation_quality", "clinical_ls", "annotator_confidence",
    "reviewed_attempt_id", "reviewed_attempt_sequence", "attempt_count",
    "prompt_type", "prompt_data_json", "model_name", "model_config",
    "checkpoint_name", "selected_index", "selected_score", "mask_area_pixels",
    "mask_area_ratio", "prediction_time_seconds", "evaluation_created_at",
    "finalized_at",
)
SAM_METADATA_COLUMNS = (
    "model_name", "model_config", "checkpoint_name", "selected_index",
    "selected_score", "mask_area_pixels", "mask_area_ratio", "prediction_time_seconds",
)
QUALITIES = ("adequate", "partially_adequate", "inadequate")


class InconsistentEvaluation(ValueError):
    """A finalized Evaluation cannot be exported without guessing its reviewed attempt."""


def _query():
    counted = aliased(SegmentationAttempt)
    attempt_count = (select(func.count(counted.id))
                     .where(counted.evaluation_id == Evaluation.id)
                     .correlate(Evaluation)
                     .scalar_subquery())
    return (
        select(
            Evaluation.id.label("evaluation_id"),
            ClinicalCase.id.label("case_id"),
            ClinicalCase.anonymous_patient_code.label("case_code"),
            Image.id.label("image_id"),
            Image.sha256.label("image_sha256"),
            Image.width.label("image_width"),
            Image.height.label("image_height"),
            Evaluation.annotator_code,
            Evaluation.pci_region_id,
            Evaluation.segmentation_quality,
            Evaluation.clinical_ls,
            Evaluation.annotator_confidence,
            Evaluation.reviewed_attempt_id,
            Evaluation.created_at.label("evaluation_created_at"),
            Evaluation.finalized_at,
            SegmentationAttempt.id.label("attempt_id"),
            SegmentationAttempt.evaluation_id.label("attempt_evaluation_id"),
            SegmentationAttempt.sequence_number.label("reviewed_attempt_sequence"),
            SegmentationAttempt.prompt_type,
            SegmentationAttempt.prompt_data,
            SegmentationAttempt.sam_metadata,
            attempt_count.label("attempt_count"),
        )
        .join(Image, Image.id == Evaluation.image_id)
        .join(ClinicalCase, ClinicalCase.id == Image.case_id)
        .outerjoin(SegmentationAttempt, SegmentationAttempt.id == Evaluation.reviewed_attempt_id)
        .where(Evaluation.status == "finalized")
        .order_by(Evaluation.finalized_at, Evaluation.id)
    )


def _problem(record) -> str | None:
    if record.reviewed_attempt_id is None:
        return "missing reviewed_attempt_id"
    if record.attempt_id is None:
        return f"reviewed attempt {record.reviewed_attempt_id} does not exist"
    if record.attempt_evaluation_id != record.evaluation_id:
        return f"reviewed attempt {record.reviewed_attempt_id} belongs to another evaluation"
    if record.segmentation_quality not in QUALITIES:
        return "missing or invalid segmentation_quality"
    if record.finalized_at is None:
        return "missing finalized_at"
    return None


def _timestamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat()


def _row(record) -> dict[str, Any]:
    row = {name: getattr(record, name) for name in COLUMNS
           if name not in SAM_METADATA_COLUMNS and name != "prompt_data_json"}
    metadata = record.sam_metadata or {}
    row.update({name: metadata.get(name) for name in SAM_METADATA_COLUMNS})
    row["prompt_data_json"] = json.dumps(record.prompt_data, sort_keys=True,
                                         separators=(",", ":"), ensure_ascii=False)
    row["evaluation_created_at"] = _timestamp(record.evaluation_created_at)
    row["finalized_at"] = _timestamp(record.finalized_at)
    return row


def load_rows(connection: Connection) -> list[dict[str, Any]]:
    records = connection.execute(_query()).all()
    problems = [(r.evaluation_id, p) for r in records if (p := _problem(r))]
    if problems:
        details = "; ".join(f"evaluation_id={eid}: {problem}" for eid, problem in problems)
        raise InconsistentEvaluation(
            f"Export aborted: {len(problems)} inconsistent finalized evaluation(s). {details}")
    return [_row(r) for r in records]


def read_rows(engine: Engine) -> list[dict[str, Any]]:
    """Read inside a READ ONLY transaction that is always rolled back."""
    with engine.connect() as connection:
        with connection.begin() as transaction:
            connection.execute(text("SET TRANSACTION READ ONLY"))
            rows = load_rows(connection)
            transaction.rollback()
    return rows


def _cell(value: Any) -> Any:
    if value is None:
        return ""
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, (dict, list)):
        return json.dumps(value, sort_keys=True, separators=(",", ":"))
    return value


def write_csv(rows: list[dict[str, Any]], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows({name: _cell(row[name]) for name in COLUMNS} for row in rows)


def export_experiment_b(engine: Engine, output: Path) -> list[dict[str, Any]]:
    rows = read_rows(engine)
    write_csv(rows, output)
    return rows


def format_summary(rows: list[dict[str, Any]], output: Path | str) -> str:
    """Operational check of the exported set; not a statistical analysis."""
    quality = Counter(row["segmentation_quality"] for row in rows)
    region = sum(row["pci_region_id"] is not None for row in rows)
    ls = sum(row["clinical_ls"] is not None for row in rows)
    lines = [
        f"Exported {len(rows)} finalized evaluations",
        f"Output: {output}",
        "",
        "Segmentation quality:",
        *(f"  {name}: {quality[name]}" for name in QUALITIES),
        "",
        "PCI region:",
        f"  determined: {region}",
        f"  undetermined: {len(rows) - region}",
        "",
        "Clinical LS:",
        f"  determined: {ls}",
        f"  undetermined: {len(rows) - ls}",
    ]
    return "\n".join(lines)
