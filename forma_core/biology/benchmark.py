"""CLI for validating biological experiment metadata against a Forma fluidic project."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from forma_core.fluidics.validation import validate_fluidic_system
from forma_core.workspaces.projects.models import HardwareIntermediateRepresentation

from .models import BiologicalExperiment
from .validation import validate_biological_experiment


def evaluate_biological_scenario(
    experiment: BiologicalExperiment,
    project: HardwareIntermediateRepresentation,
) -> dict[str, Any]:
    """Return deterministic physical/interface checks without predicting biology."""

    fluidic_issues = (
        validate_fluidic_system(project.fluidic_system)
        if project.fluidic_system is not None
        else []
    )
    biological_issues = validate_biological_experiment(experiment, project.fluidic_system)
    return {
        "experiment_id": experiment.id,
        "organ_model": experiment.organ_model,
        "passed": not fluidic_issues and not biological_issues,
        "counts": {
            "compartments": len(experiment.compartments),
            "exposures": len(experiment.exposures),
            "controls": len(experiment.controls),
            "endpoints": len(experiment.endpoints),
            "sampling_points": len(experiment.sampling_points),
            "datasets": len(experiment.datasets),
            "observations": len(experiment.observations),
            "reference_outcomes": len(experiment.reference_outcomes),
        },
        "fluidic_issues": [issue.model_dump(mode="json") for issue in fluidic_issues],
        "biological_issues": [issue.model_dump(mode="json") for issue in biological_issues],
        "claims": {
            "toxicity_prediction": False,
            "biological_simulation": False,
            "clinical_safety_assessment": False,
        },
    }


def build_parser() -> argparse.ArgumentParser:
    """Build the command-line parser used by the submission/demo workflow."""

    parser = argparse.ArgumentParser(
        description="Validate a biological experiment scenario against a Forma fluidic Hardware IR project."
    )
    parser.add_argument("experiment", type=Path, help="BiologicalExperiment JSON file.")
    parser.add_argument("--project", required=True, type=Path, help="Forma Hardware IR JSON containing fluidic_system.")
    parser.add_argument("--output", type=Path, help="Optional path for the JSON result.")
    return parser


def main(argv: list[str] | None = None) -> int:
    """Validate the scenario, print canonical JSON and return a CI-friendly code."""

    args = build_parser().parse_args(argv)
    experiment = BiologicalExperiment.model_validate_json(args.experiment.read_text())
    project = HardwareIntermediateRepresentation.model_validate_json(args.project.read_text())
    result = evaluate_biological_scenario(experiment, project)
    payload = json.dumps(result, indent=2, sort_keys=True)
    print(payload)
    if args.output is not None:
        args.output.write_text(payload + "\n")
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
