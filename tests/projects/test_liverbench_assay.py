"""Synthetic-only tests for local assay ingestion, abstention and leakage boundaries."""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from forma_core.biology.liverbench import LiverBenchDataset, load_liverbench
from forma_core.biology.liverbench_assay import (
    AssayDataset,
    build_assay_baseline,
    evaluate_assay_baseline,
    load_assay_csvs,
    main,
)

ROOT = Path(__file__).resolve().parents[2]
DATASET = ROOT / "examples/biology/liverbench-v0.json"


def synthetic_inputs(tmp_path: Path, *, full: bool = False) -> tuple[LiverBenchDataset, Path, Path]:
    """Create explicitly artificial assay values; none are DILImap measurements."""
    dataset = load_liverbench(DATASET)
    viability, cmax = tmp_path / "synthetic_viability.csv", tmp_path / "synthetic_cmax.csv"
    records = [r for r in dataset.records if r.split == "heldout"]
    with viability.open("w", newline="") as vf, cmax.open("w", newline="") as cf:
        vw, cw = csv.writer(vf), csv.writer(cf)
        vw.writerow(["Compound", "IC10_uM"])
        cw.writerow(["LIBRARY CMPDS", "Cmax_median"])
        for i, record in enumerate(records if full else records[:3]):
            vw.writerow([record.compound_name, (79, 80, 81, 40, 90, 100)[i] if full or i != 2 else ""])
            cw.writerow([record.compound_name, 1])
    return dataset, viability, cmax


def load_synthetic(tmp_path: Path, *, full: bool = False) -> tuple[LiverBenchDataset, AssayDataset]:
    """Load synthetic CSVs using the same public adapter as real local inputs."""
    dataset, viability, cmax = synthetic_inputs(tmp_path, full=full)
    return dataset, load_assay_csvs(dataset, viability, cmax, source_uri="urn:test:synthetic-only")


def test_partial_coverage_abstains_and_suppresses_metrics(tmp_path: Path) -> None:
    """Blank IC10 and missing compounds must not silently become negatives."""
    dataset, assays = load_synthetic(tmp_path)
    result = evaluate_assay_baseline(dataset, assays)
    assert result["coverage"]["predicted_records"] == 2
    assert result["coverage"]["abstained_records"] == 4
    assert result["evaluation"]["complete"] is False
    assert result["evaluation"]["metrics"] is None
    details = {row["record_id"]: row for row in result["prediction_details"]}
    assert details["simvastatin"]["reasons"] == ["missing_ic10_estimate"]
    assert details["zolpidem"]["reasons"] == ["missing_ic10_source_row", "missing_cmax_source_row"]


def test_threshold_is_strict_and_score_is_monotone(tmp_path: Path) -> None:
    """Synthetic margins of 79, 80 and 81 exercise the published rule's boundary."""
    dataset, assays = load_synthetic(tmp_path, full=True)
    bundle, _ = build_assay_baseline(dataset, assays)
    assert bundle is not None
    predictions = bundle.predictions
    assert [p.predicted_label for p in predictions[:3]] == [1, 0, 0]
    assert predictions[0].score > predictions[1].score > predictions[2].score
    result = evaluate_assay_baseline(dataset, assays)
    assert result["evaluation"]["complete"] is True
    assert result["evaluation"]["metrics"]["n"] == 6


def test_prediction_generation_ignores_all_fda_fields(tmp_path: Path) -> None:
    """Perturb evaluation labels and DILIrank metadata without changing predictions."""
    dataset, assays = load_synthetic(tmp_path, full=True)
    before = build_assay_baseline(dataset, assays)
    # Deliberately bypass label/cohort validators for this adversarial leakage test.
    altered = dataset.model_copy(update={"records": [r.model_copy(update={
        "dilist_classification": 1 - r.dilist_classification, "severity_class": 8 - r.severity_class,
        "dilirank_concern": "Ambiguous-DILI-concern", "cohort": "challenge_negative",
    }) for r in dataset.records]})
    assert build_assay_baseline(altered, assays) == before


@pytest.mark.parametrize("bad_value", ["0", "-1", "inf", "-inf", "oops"])
def test_invalid_measurements_are_rejected(tmp_path: Path, bad_value: str) -> None:
    """Reject corrupt values rather than silently classifying them."""
    dataset, viability, cmax = synthetic_inputs(tmp_path)
    cmax.write_text(f"LIBRARY CMPDS,Cmax_median\nKetoconazole,{bad_value}\n")
    with pytest.raises(ValueError):
        load_assay_csvs(dataset, viability, cmax, source_uri="urn:test:synthetic-only")


def test_duplicate_name_is_not_resolved_by_row_order(tmp_path: Path) -> None:
    """Case-insensitive duplicate names require explicit upstream resolution."""
    dataset, viability, cmax = synthetic_inputs(tmp_path)
    viability.write_text("Compound,IC10_uM\nKetoconazole,10\n ketoconazole ,20\n")
    with pytest.raises(ValueError, match="duplicate"):
        load_assay_csvs(dataset, viability, cmax, source_uri="urn:test:synthetic-only")


def test_synonyms_and_salt_forms_are_not_guessed(tmp_path: Path) -> None:
    """A related chemical name cannot accidentally populate a benchmark row."""
    dataset, viability, cmax = synthetic_inputs(tmp_path)
    viability.write_text("Compound,IC10_uM\nValproate sodium,10\n")
    assays = load_assay_csvs(dataset, viability, cmax, source_uri="urn:test:synthetic-only")
    assert all(record.ic10_um is None for record in assays.records)
    result = evaluate_assay_baseline(dataset, assays)
    assert result["predictions"] is None
    assert result["coverage"]["abstained_records"] == 6


def test_content_hash_changes_with_input_bytes(tmp_path: Path) -> None:
    """Provenance identifies the actual input, not just its filename."""
    dataset, viability, cmax = synthetic_inputs(tmp_path)
    before = load_assay_csvs(dataset, viability, cmax, source_uri="urn:test:synthetic-only")
    viability.write_text(viability.read_text().replace(",79", ",78"))
    after = load_assay_csvs(dataset, viability, cmax, source_uri="urn:test:synthetic-only")
    assert before.sources[0].sha256 != after.sources[0].sha256
    assert before.sources[1].sha256 == after.sources[1].sha256


def test_schema_and_identity_errors_fail_closed(tmp_path: Path) -> None:
    """Reject missing required headers, IDs and incompatible source names."""
    dataset, assays = load_synthetic(tmp_path)
    with pytest.raises(ValueError, match="every benchmark ID"):
        build_assay_baseline(dataset, assays.model_copy(update={"records": assays.records[:-1]}))
    bad = assays.model_dump()
    bad["records"][0]["ic10_um"] = 1.0
    with pytest.raises(ValueError, match="named source row"):
        AssayDataset.model_validate(bad)
    bad = assays.model_dump()
    bad["records"][0]["compound_name"] = "wrong identity"
    with pytest.raises(ValueError, match="identity mismatch"):
        build_assay_baseline(dataset, AssayDataset.model_validate(bad))
    wrong = tmp_path / "wrong.csv"
    wrong.write_text("Compound,wrong_column\nKetoconazole,1\n")
    with pytest.raises(ValueError, match="requires columns"):
        load_assay_csvs(dataset, wrong, wrong, source_uri="urn:test:synthetic-only")


def test_cli_distinguishes_successful_audit_from_complete_evaluation(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Coverage audits succeed, while an explicit complete-evaluation gate fails."""
    _, viability, cmax = synthetic_inputs(tmp_path)
    output = tmp_path / "audit.json"
    args = [str(DATASET), str(viability), str(cmax), "--source-uri", "urn:test:synthetic-only", "--output", str(output)]
    assert main(args) == 0
    assert json.loads(output.read_text()) == json.loads(capsys.readouterr().out)
    assert main([*args, "--require-complete"]) == 2
