"""Scientific regression and uncertainty checks for the external Ewart reproduction."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from forma_core.biology.ewart_liverchip import (
    EwartDataset, Margin, build_report, classify_margin, load_dataset, main,
    parse_margin, predict_margins, summarize_observations,
)

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "examples/biology/ewart-liverchip-v0.json"
REPORT = ROOT / "examples/biology/ewart-liverchip-v0-report.json"


@pytest.fixture
def dataset() -> EwartDataset:
    """Load the frozen external data without a network or workbook dependency."""
    return load_dataset(DATA)


def test_published_reproduction_and_known_discrepancy(dataset: EwartDataset) -> None:
    """Require computed counts, including the unresolved donor-2 disagreement."""
    report = build_report(dataset)
    expected = {"chip_donor1": (16, 5, 0, 6), "chip_donor2": (10, 3, 0, 5),
                "chip_both": (12, 3, 0, 3), "spheroid": (8, 2, 1, 11)}
    for model, values in expected.items():
        assert report["uncorrected_reproduction"][model]["confusion_matrix"] == dict(zip(("tp", "tn", "fp", "fn"), values))
    assert report["mismatched_models"] == ["chip_donor2"]
    both = report["uncorrected_reproduction"]["chip_both"]
    assert (both["n_classified"], both["sensitivity"], both["specificity"]) == (18, 0.8, 1.0)
    assert report["corrected_analysis"]["status"] == "not_reproduced"
    assert not report["claims"]["independent_predictor_validation"]


@pytest.mark.parametrize("raw,paper,interval", [
    ("50", 1, 1), ("50.1", 0, 0), (">3", 0, None), (">50", 0, 0),
    ("> 108", 0, 0), ("<50", 1, 1), ("<51", None, None), ("–", None, None),
    ("22,500", 0, 0), ("0", 1, 1),
])
def test_censored_boundaries(raw: str, paper: int | None, interval: int | None) -> None:
    """Keep exact, missing and bounded results distinct at the decision boundary."""
    assert classify_margin(Margin(raw=raw), "paper_convention") == paper
    assert classify_margin(Margin(raw=raw), "interval_aware") == interval


@pytest.mark.parametrize("raw", ["nan", "inf", "-1", "<0", "approx 3", "", "1e3"])
def test_invalid_margins(raw: str) -> None:
    """Reject unrecognized or impossible printed ranges."""
    with pytest.raises(ValueError):
        parse_margin(raw)


def test_predictions_do_not_read_reference_labels(dataset: EwartDataset) -> None:
    """Changing labels cannot change any MOS-derived decision."""
    changed = dataset.model_copy(deep=True)
    for compound in changed.compounds:
        compound.reference_label = 1 - compound.reference_label
    assert predict_margins(dataset, "chip_both", "paper_convention") == predict_margins(changed, "chip_both", "paper_convention")


def test_interval_abstentions_are_excluded_and_counted(dataset: EwartDataset) -> None:
    """Expose the smaller evaluated population under interval uncertainty."""
    both = build_report(dataset)["interval_aware_audit"]["chip_both"]
    assert (both["n_classified"], both["n_indeterminate"], both["n_not_tested"]) == (14, 4, 9)
    assert both["matches_published_counts"] is None


def test_observations_missingness_and_descriptive_statistics(dataset: EwartDataset) -> None:
    """Preserve all 210 rows but exclude six missing values from means and SEM."""
    assert len(dataset.compounds) == 27
    assert len(dataset.observations) == 210
    assert sum(o.value is not None for o in dataset.observations) == 204
    assert {o.source_missing_marker for o in dataset.observations if o.value is None} == {"NA", "NaN"}
    summary = summarize_observations(dataset)
    assert len(summary) == 105
    empty = [g for g in summary if g["n"] == 0]
    assert len(empty) == 2
    assert all(g["mean"] is None and g["sem"] is None and g["n_missing"] == 2 for g in empty)
    first = next(g for g in summary if g["compound_id"] == "clozapine" and g["endpoint"] == "albumin" and g["dose_cmax_multiple"] == 1)
    assert first["mean"] == pytest.approx((135.709948005764 + 113.769799561393) / 2)
    assert first["sem"] == pytest.approx(abs(135.709948005764 - 113.769799561393) / 2)
    assert first["unit"] == "percent_of_control"


@pytest.mark.parametrize("mutation", ["duplicate_row", "unknown_compound", "wrong_unit", "unmarked_missing", "nan", "wrong_label"])
def test_invalid_dataset_relationships(dataset: EwartDataset, mutation: str) -> None:
    """Reject provenance, label, unit and missing-value corruption."""
    data = dataset.model_dump()
    if mutation == "duplicate_row":
        data["observations"].append(data["observations"][0])
    elif mutation == "unknown_compound":
        data["observations"][0]["compound_id"] = "unknown"
    elif mutation == "wrong_unit":
        data["observations"][0]["unit"] = "morphology_score"
    elif mutation == "unmarked_missing":
        data["observations"][0]["value"] = None
    elif mutation == "nan":
        data["observations"][0]["value"] = float("nan")
    else:
        data["compounds"][0]["reference_label"] = 1
    with pytest.raises(ValidationError):
        EwartDataset.model_validate(data)


def test_frozen_report_and_cli(dataset: EwartDataset, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Audit succeeds, while opt-in full-reproduction gating fails transparently."""
    assert build_report(dataset) == json.loads(REPORT.read_text())
    output = tmp_path / "report.json"
    assert main([str(DATA), "--output", str(output)]) == 0
    assert output.read_bytes() == REPORT.read_bytes()
    assert main([str(DATA), "--require-all-uncorrected-matches"]) == 2
    capsys.readouterr()


def test_importer_rejects_changed_sources(tmp_path: Path) -> None:
    """Do not silently accept a changed publication under the frozen version."""
    spec = importlib.util.spec_from_file_location("ewart_builder", ROOT / "scripts/biology/build_ewart_dataset.py")
    assert spec and spec.loader
    builder = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(builder)
    source = tmp_path / "article.xml"
    source.write_text("changed")
    with pytest.raises(ValueError, match="SHA256 mismatch"):
        builder.verify_source(source, "article")
