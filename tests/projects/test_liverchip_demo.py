"""End-to-end artifact and failure checks for the submission demo."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from forma_core.biology.liverchip_demo import run_demo
from forma_core.biology.models import BiologicalExperiment

ROOT = Path(__file__).resolve().parents[2]


def test_complete_demo_exports_actual_results(tmp_path: Path) -> None:
    """Run all components and verify typed outputs and published missingness."""
    result = run_demo(ROOT, tmp_path)
    assert result["passed"]
    assert len(result["fault_cases"]) == 3
    assert all(c["detected"] and c["after"]["passed"] for c in result["fault_cases"])
    assert all(p["passed"] for p in result["flow_perturbations"])
    assert result["evidence_summary"]["measured_values"] == 32
    assert result["evidence_summary"]["missing_values"] == 4
    experiment = BiologicalExperiment.model_validate_json((tmp_path / "experiment.json").read_text())
    assert len(experiment.observations) == 36
    assert json.loads((tmp_path / "run.json").read_text()) == result
    molecular = json.loads((tmp_path / "molecular-baseline.json").read_text())
    assert molecular["evaluation"]["complete"]
    assert (tmp_path / "REPORT.md").exists()
    with pytest.raises(ValueError, match="new or empty"):
        run_demo(ROOT, tmp_path)


def test_unknown_compound_leaves_no_partial_package(tmp_path: Path) -> None:
    """Reject unrecognized evidence selection before producing any run artifact."""
    output = tmp_path / "invalid"
    with pytest.raises(ValueError, match="Unknown compound"):
        run_demo(ROOT, output, "not-a-known-compound")
    assert not output.exists()
