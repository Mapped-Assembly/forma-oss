"""End-to-end evidence selection, provenance and backward-compatibility checks."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from forma_core.biology.benchmark import evaluate_biological_scenario
from forma_core.biology.ewart_liverchip import EwartDataset, load_dataset
from forma_core.biology.liverchip_evidence import build_evidence_experiment, build_evidence_report, main
from forma_core.biology.models import BiologicalExperiment, BiologicalObservation
from forma_core.workspaces.projects.models import HardwareIntermediateRepresentation

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "examples/biology/ewart-liverchip-v0.json"
TEMPLATE = ROOT / "examples/organ-on-chip/liver-dili-biological.json"
PROJECT = ROOT / "examples/organ-on-chip/two-channel.json"
EXAMPLE = ROOT / "examples/organ-on-chip/liver-dili-ewart-biological.json"


@pytest.fixture
def context() -> tuple[EwartDataset, BiologicalExperiment, HardwareIntermediateRepresentation]:
    """Load the external dataset, existing template and physical fixture offline."""
    return (load_dataset(DATA), BiologicalExperiment.model_validate_json(TEMPLATE.read_text()),
            HardwareIntermediateRepresentation.model_validate_json(PROJECT.read_text()))


def test_all_source_rows_preserved(context: tuple) -> None:
    """Across six compounds, preserve every value, dose, unit, bound and source row."""
    dataset, template, project = context
    before = template.model_dump()
    total, missing = 0, 0
    for compound_id in sorted({o.compound_id for o in dataset.observations}):
        experiment = build_evidence_experiment(dataset, compound_id.upper(), template)
        source_rows = [o for o in dataset.observations if o.compound_id == compound_id]
        assert len(experiment.observations) == len(source_rows)
        source_hash = next(s.sha256 for s in dataset.sources if s.id == "supplement8")
        assert next(s.sha256 for s in experiment.datasets if s.id == "ewart_supplement8") == source_hash
        for actual, source in zip(experiment.observations, source_rows):
            assert (actual.numeric_value, actual.dose_value, actual.unit) == (source.value, source.dose_cmax_multiple, source.unit)
            assert actual.source_record_id == f"{source.source_sheet}:row{source.source_row}"
            assert actual.source_missing_marker == source.source_missing_marker
            assert actual.compound_identifier == compound_id
            assert actual.time_h == 72
            total += 1
            missing += actual.measurement_status == "missing"
        report = build_evidence_report(dataset, experiment, project)
        assert report["validation"]["passed"]
        assert report["claims"]["fixture_generated_measurements"] is False
        assert not experiment.exposures and not experiment.controls and not experiment.sampling_points
        assert BiologicalExperiment.model_validate_json(experiment.model_dump_json()) == experiment
    assert (total, missing) == (210, 6)
    assert template.model_dump() == before


def test_partial_missing_and_unavailable_evidence(context: tuple) -> None:
    """Distinguish source missing values from compounds lacking any response rows."""
    dataset, template, project = context
    expected = {"Troglitazone": "partial", "Clozapine": "complete", "Ambrisentan": "unavailable"}
    for name, status in expected.items():
        experiment = build_evidence_experiment(dataset, name, template)
        report = build_evidence_report(dataset, experiment, project)
        assert report["evidence"]["status"] == status
        assert report["validation"]["passed"]
        if status == "unavailable":
            assert report["evidence"]["source_rows"] == 0
            assert report["evidence"]["dose_response_summary"] == []
            assert report["evidence"]["reason"]
            assert report["evidence"]["published_margins"]["chip_donor1"] == ">3"
        if name == "Troglitazone":
            assert report["evidence"]["missing_values"] == 4
            assert sum(g["n_missing"] for g in report["evidence"]["dose_response_summary"]) == 4


def test_invalid_selection_and_compartment(context: tuple) -> None:
    """Do not fuzzy-match an unknown drug or attach data to a nonexistent compartment."""
    dataset, template, _ = context
    with pytest.raises(ValueError, match="Unknown compound"):
        build_evidence_experiment(dataset, "Acetaminophen", template)
    with pytest.raises(ValueError, match="Unknown template compartment"):
        build_evidence_experiment(dataset, "Clozapine", template, "missing")


def test_existing_template_and_frozen_evidence_example(context: tuple) -> None:
    """Keep the prior metadata example valid and make the new example reproducible."""
    dataset, template, project = context
    assert evaluate_biological_scenario(template, project)["passed"]
    experiment = build_evidence_experiment(dataset, "  troglitazone  ", template)
    assert experiment.model_dump(mode="json") == json.loads(EXAMPLE.read_text())
    assert all(o.subject != "Acetaminophen" for o in experiment.reference_outcomes)


@pytest.mark.parametrize("updates", [
    {"measurement_status": "missing"},
    {"measurement_status": "missing", "missing_reason": "absent"},
    {"numeric_value": None},
    {"missing_reason": "absent"},
    {"source_missing_marker": "NA"},
    {"dose_value": 1},
    {"dose_unit": "human_cmax_multiple"},
    {"dose_value": 1, "dose_unit": "human_cmax_multiple"},
    {"dose_value": -1, "dose_unit": "human_cmax_multiple", "compound_identifier": "drug"},
])
def test_observation_rejects_ambiguous_metadata(updates: dict[str, Any]) -> None:
    """Missing values cannot masquerade as measurements; dose context must be complete."""
    payload = {"id": "obs", "endpoint_id": "alt", "compartment_id": "liver", "time_h": 72,
               "numeric_value": 1.0, "dataset_ref_id": "source", **updates}
    with pytest.raises(ValidationError):
        BiologicalObservation.model_validate(payload)


def cli_args(compound: str) -> list[str]:
    """Provide required offline CLI inputs with an explicit compound selection."""
    return [str(DATA), "--compound", compound, "--template", str(TEMPLATE), "--project", str(PROJECT)]


def test_cli_exports_and_legacy_benchmark(context: tuple, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Export valid standalone metadata and a complete report from one CLI command."""
    _, _, project = context
    report_path, experiment_path = tmp_path / "report.json", tmp_path / "experiment.json"
    assert main(cli_args("Troglitazone") + ["--output", str(report_path), "--experiment-output", str(experiment_path)]) == 0
    report = json.loads(report_path.read_text())
    assert report["derived_dataset_sha256"] == hashlib.sha256(DATA.read_bytes()).hexdigest()
    assert report["experiment"] == json.loads(experiment_path.read_text())
    assert evaluate_biological_scenario(BiologicalExperiment.model_validate_json(experiment_path.read_text()), project)["passed"]
    first = report_path.read_bytes()
    assert main(cli_args("Troglitazone") + ["--output", str(report_path)]) == 0
    assert first == report_path.read_bytes()
    capsys.readouterr()


def test_cli_rejects_input_overwrite_and_unknown_drug(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Reject unsafe output aliases and invalid selection before producing artifacts."""
    for options in [cli_args("Clozapine") + ["--output", str(DATA)],
                    cli_args("Clozapine") + ["--output", str(tmp_path / "same"), "--experiment-output", str(tmp_path / "same")],
                    cli_args("unknown") + ["--output", str(tmp_path / "unknown.json")]]:
        with pytest.raises(SystemExit) as error:
            main(options)
        assert error.value.code == 2
    assert not (tmp_path / "unknown.json").exists()
    capsys.readouterr()


def test_invalid_physical_mapping_fails_cli(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """A response dataset must not hide broken physical fixture references."""
    template = json.loads(TEMPLATE.read_text())
    template["compartments"][0]["fluidic_component_ids"] = ["missing_channel"]
    path = tmp_path / "invalid.json"
    path.write_text(json.dumps(template))
    args = cli_args("Clozapine")
    args[args.index("--template") + 1] = str(path)
    assert main(args) == 1
    report = json.loads(capsys.readouterr().out)
    assert report["validation"]["biological_issues"][0]["code"] == "unknown_fluidic_component"
