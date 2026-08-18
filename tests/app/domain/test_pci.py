from __future__ import annotations

from dataclasses import asdict

import pytest

from backend.app.domain.pci import (
    MAXIMUM_PCI_TOTAL,
    PCIObservation,
    PCI_REGIONS,
    compose_pci,
)


def observation(
    observation_id: str,
    region_id: int,
    ls_score: int,
) -> PCIObservation:
    return PCIObservation(observation_id, region_id, ls_score)


def test_catalog_has_exactly_thirteen_regions() -> None:
    assert len(PCI_REGIONS) == 13


def test_catalog_ids_are_zero_through_twelve() -> None:
    assert [region.region_id for region in PCI_REGIONS] == list(range(13))


@pytest.mark.parametrize("ls_score", [0, 3])
def test_minimum_and_maximum_ls_are_valid(ls_score: int) -> None:
    assert observation("obs", 0, ls_score).ls_score == ls_score


@pytest.mark.parametrize("region_id", [-1, 13])
def test_invalid_region_is_rejected(region_id: int) -> None:
    with pytest.raises(ValueError, match="region_id"):
        observation("obs", region_id, 0)


@pytest.mark.parametrize("ls_score", [-1, 4, True])
def test_invalid_ls_is_rejected(ls_score: int) -> None:
    with pytest.raises(ValueError, match="ls_score"):
        observation("obs", 0, ls_score)  # type: ignore[arg-type]


def test_empty_observation_id_is_rejected() -> None:
    with pytest.raises(ValueError, match="observation_id"):
        observation(" ", 0, 1)


def test_duplicate_observation_is_rejected() -> None:
    with pytest.raises(ValueError, match="duplicate observation_id"):
        compose_pci((observation("same", 0, 1), observation("same", 1, 2)))


def test_ls_zero_marks_region_as_assessed() -> None:
    result = compose_pci((observation("zero", 0, 0),))
    assert result.assessed_regions == (0,)
    assert 0 not in result.pending_regions


def test_missing_region_remains_pending() -> None:
    result = compose_pci((observation("obs", 0, 1),))
    assert result.pending_regions == tuple(range(1, 13))


def test_partial_subtotal_sums_assessed_regions_only() -> None:
    result = compose_pci(
        (observation("a", 0, 1), observation("b", 5, 3))
    )
    assert result.subtotal == 4


def test_incomplete_composition_has_no_pci_total() -> None:
    result = compose_pci((observation("obs", 0, 1),))
    assert result.status == "incomplete"
    assert result.pci_total is None


def test_complete_pci_can_be_zero() -> None:
    result = compose_pci(
        tuple(observation(f"obs-{region}", region, 0) for region in range(13))
    )
    assert result.status == "complete"
    assert result.subtotal == result.pci_total == 0


def test_complete_pci_can_be_thirty_nine() -> None:
    result = compose_pci(
        tuple(observation(f"obs-{region}", region, 3) for region in range(13))
    )
    assert result.subtotal == result.pci_total == MAXIMUM_PCI_TOTAL == 39


def test_multiple_observations_use_maximum_ls() -> None:
    result = compose_pci(
        (
            observation("low", 2, 1),
            observation("high", 2, 3),
            observation("middle", 2, 2),
        )
    )
    assert result.regional_scores[0].ls_score == 3
    assert result.regional_scores[0].observations_count == 3
    assert result.regional_scores[0].aggregation == "maximum"


def test_source_observation_is_selected_maximum() -> None:
    result = compose_pci(
        (observation("low", 7, 1), observation("high", 7, 3))
    )
    assert result.regional_scores[0].source_observation_id == "high"


def test_equal_maximum_uses_deterministic_observation_id() -> None:
    first = compose_pci(
        (observation("z", 0, 3), observation("a", 0, 3))
    )
    second = compose_pci(
        (observation("a", 0, 3), observation("z", 0, 3))
    )
    assert first == second
    assert first.regional_scores[0].source_observation_id == "a"


def test_input_sequence_is_not_modified() -> None:
    items = [observation("b", 2, 2), observation("a", 0, 1)]
    before = [asdict(item) for item in items]
    compose_pci(items)
    assert [asdict(item) for item in items] == before


def test_protocol_version_is_explicit() -> None:
    result = compose_pci(())
    assert result.protocol_id == "sugarbaker_pci"
    assert result.protocol_version == "project-defined-v1"
    assert result.maximum_possible_total == 39
