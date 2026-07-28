"""Pure composition rules for the project-defined PCI protocol."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Sequence


PROTOCOL_ID = "sugarbaker_pci"
PROTOCOL_VERSION = "project-defined-v1"
MAXIMUM_PCI_TOTAL = 39


@dataclass(frozen=True, slots=True)
class PCIRegion:
    region_id: int
    code: str
    display_name: str


PCI_REGIONS: tuple[PCIRegion, ...] = (
    PCIRegion(0, "central", "Central"),
    PCIRegion(1, "right_upper", "Right upper"),
    PCIRegion(2, "epigastrium", "Epigastrium"),
    PCIRegion(3, "left_upper", "Left upper"),
    PCIRegion(4, "left_flank", "Left flank"),
    PCIRegion(5, "left_lower", "Left lower"),
    PCIRegion(6, "pelvis", "Pelvis"),
    PCIRegion(7, "right_lower", "Right lower"),
    PCIRegion(8, "right_flank", "Right flank"),
    PCIRegion(9, "upper_jejunum", "Upper jejunum"),
    PCIRegion(10, "lower_jejunum", "Lower jejunum"),
    PCIRegion(11, "upper_ileum", "Upper ileum"),
    PCIRegion(12, "lower_ileum", "Lower ileum"),
)
REGIONS_BY_ID = {region.region_id: region for region in PCI_REGIONS}


@dataclass(frozen=True, slots=True)
class PCIObservation:
    observation_id: str
    region_id: int
    ls_score: int
    ls_source: Literal["user"] = "user"
    analysis_id: str | None = None

    def __post_init__(self) -> None:
        if not self.observation_id or not self.observation_id.strip():
            raise ValueError("observation_id must not be empty.")
        if self.region_id not in REGIONS_BY_ID:
            raise ValueError("region_id must be between 0 and 12.")
        if isinstance(self.ls_score, bool) or self.ls_score not in range(4):
            raise ValueError("ls_score must be between 0 and 3.")
        if self.ls_source != "user":
            raise ValueError("ls_source must be 'user' in this protocol version.")


@dataclass(frozen=True, slots=True)
class RegionalPCIScore:
    region_id: int
    region_name: str
    ls_score: int
    source_observation_id: str
    observations_count: int
    aggregation: Literal["maximum"] = "maximum"


@dataclass(frozen=True, slots=True)
class PCIComposition:
    status: Literal["incomplete", "complete"]
    regional_scores: tuple[RegionalPCIScore, ...]
    assessed_regions: tuple[int, ...]
    pending_regions: tuple[int, ...]
    subtotal: int
    pci_total: int | None
    maximum_possible_total: int
    protocol_id: str
    protocol_version: str


def get_region(region_id: int) -> PCIRegion:
    try:
        return REGIONS_BY_ID[region_id]
    except KeyError as exc:
        raise ValueError("region_id must be between 0 and 12.") from exc


def compose_pci(
    observations: Sequence[PCIObservation],
    *,
    protocol_id: str = PROTOCOL_ID,
    protocol_version: str = PROTOCOL_VERSION,
) -> PCIComposition:
    """Aggregate the maximum user-provided LS for every assessed region."""
    if protocol_id != PROTOCOL_ID:
        raise ValueError(f"protocol_id must be '{PROTOCOL_ID}'.")
    if protocol_version != PROTOCOL_VERSION:
        raise ValueError(f"protocol_version must be '{PROTOCOL_VERSION}'.")

    observation_ids: set[str] = set()
    grouped: dict[int, list[PCIObservation]] = {}
    for observation in observations:
        if observation.observation_id in observation_ids:
            raise ValueError(
                f"duplicate observation_id: {observation.observation_id}"
            )
        observation_ids.add(observation.observation_id)
        grouped.setdefault(observation.region_id, []).append(observation)

    regional_scores: list[RegionalPCIScore] = []
    for region_id in sorted(grouped):
        region_observations = grouped[region_id]
        selected = min(
            region_observations,
            key=lambda item: (-item.ls_score, item.observation_id),
        )
        region = get_region(region_id)
        regional_scores.append(
            RegionalPCIScore(
                region_id=region_id,
                region_name=region.code,
                ls_score=selected.ls_score,
                source_observation_id=selected.observation_id,
                observations_count=len(region_observations),
            )
        )

    assessed = tuple(score.region_id for score in regional_scores)
    pending = tuple(
        region.region_id for region in PCI_REGIONS if region.region_id not in grouped
    )
    subtotal = sum(score.ls_score for score in regional_scores)
    complete = not pending
    return PCIComposition(
        status="complete" if complete else "incomplete",
        regional_scores=tuple(regional_scores),
        assessed_regions=assessed,
        pending_regions=pending,
        subtotal=subtotal,
        pci_total=subtotal if complete else None,
        maximum_possible_total=MAXIMUM_PCI_TOTAL,
        protocol_id=protocol_id,
        protocol_version=protocol_version,
    )
