"""Existing deterministic selection validation, shared without importing SAM."""

import numpy as np
import pandas as pd
from .analysis import extreme_cases

TOLERANCE = 1e-6
REASONS = ("lowest_dice", "highest_dice", "smallest_predicted_reference_area_ratio",
           "largest_predicted_reference_area_ratio")
IDENTITY = ("image_id", "file_name", "split", "group_id")


def load_cases(source, results: pd.DataFrame) -> tuple[int, dict]:
    """Verify the quantitative selection and preserve every reason/rank pair."""
    frame = pd.read_csv(source, dtype=str, keep_default_na=False)
    required = {"annotation_id", *IDENTITY, "selection_reason", "rank"}
    if missing := required - set(frame.columns):
        raise ValueError(f"Missing cases columns: {', '.join(sorted(missing))}")
    if frame.empty:
        raise ValueError("Cases must contain at least one row.")
    for field in ("annotation_id", "image_id", "rank"):
        values = pd.to_numeric(frame[field], errors="raise")
        if not np.isfinite(values).all() or (values % 1 != 0).any():
            raise ValueError(f"Cases {field} must contain finite integers.")
        frame[field] = values.map(int)
    if (frame['rank'] < 1).any() or not frame.selection_reason.isin(REASONS).all():
        raise ValueError("Invalid selection reason or rank.")
    authoritative = results.set_index("annotation_id").to_dict("index")
    selections = {}
    for row in frame.to_dict("records"):
        aid = row["annotation_id"]
        if aid not in authoritative:
            raise ValueError(f"Selected annotation {aid} missing from results.")
        if any(row[k] != authoritative[aid][k] for k in IDENTITY):
            raise ValueError(f"Cases identity disagrees with results for annotation {aid}.")
        selections.setdefault(aid, []).append((row["selection_reason"], row["rank"]))
    columns = ["annotation_id", "selection_reason", "rank"]
    supplied = sorted(frame[columns].itertuples(index=False, name=None))
    expected = sorted(extreme_cases(results)[columns].itertuples(index=False, name=None))
    if supplied != expected:
        raise ValueError("Cases must match the deterministic quantitative selection from results.")
    return len(frame), {aid: sorted(pairs) for aid, pairs in sorted(selections.items())}

