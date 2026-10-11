"""FDA-backed LiverBench v0 dataset validation and prediction scoring.

LiverBench stores external DILI reference labels and can score predictions supplied
by another model. This module does not itself infer toxicity or clinical safety.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any, Literal

from pydantic import Field, model_validator

from forma_core.fluidics.validation import validate_fluidic_system
from forma_core.workspaces.projects.models import HardwareIntermediateRepresentation

from .models import (
    BiologicalCompartment,
    BiologicalEndpoint,
    BiologicalExperiment,
    BiologyModel,
    DatasetReference,
    Probability,
    ReferenceOutcome,
    Text,
)
from .validation import validate_biological_experiment

DILIConcern = Literal[
    "vMost-DILI-concern",
    "vLess-DILI-concern",
    "vNo-DILI-concern",
    "Ambiguous-DILI-concern",
]
BenchmarkSplit = Literal["train", "dev", "heldout"]
BenchmarkCohort = Literal[
    "clear_positive",
    "clear_negative",
    "challenge_positive",
    "challenge_negative",
]


class LiverBenchRecord(BiologyModel):
    """One compound joined across FDA DILIrank 2.0 and DILIst."""

    id: str = Field(min_length=1, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
    compound_name: Text
    dilirank_source_name: Text
    ltkbid: str = Field(pattern=r"^LT\d{5}$")
    severity_class: int = Field(ge=0, le=8)
    dilirank_concern: DILIConcern
    label_section: Text
    dilist_source_name: Text
    dilist_id: int = Field(gt=0)
    dilist_classification: Literal[0, 1]
    route: Text
    cohort: BenchmarkCohort
    split: BenchmarkSplit

    @model_validator(mode="after")
    def cohort_matches_source_labels(self) -> "LiverBenchRecord":
        """Keep the v0 cohort names mechanically tied to their FDA labels."""

        if self.cohort == "clear_positive":
            expected = self.dilist_classification == 1 and self.dilirank_concern == "vMost-DILI-concern"
        elif self.cohort == "clear_negative":
            expected = self.dilist_classification == 0 and self.dilirank_concern == "vNo-DILI-concern"
        elif self.cohort == "challenge_positive":
            expected = self.dilist_classification == 1 and self.dilirank_concern in {
                "vLess-DILI-concern", "Ambiguous-DILI-concern"
            }
        else:
            expected = self.dilist_classification == 0 and self.dilirank_concern in {
                "vLess-DILI-concern", "Ambiguous-DILI-concern"
            }
        if not expected:
            raise ValueError(
                f"LiverBench record '{self.id}' cohort '{self.cohort}' is inconsistent with its FDA labels."
            )
        return self


class LiverBenchDataset(BiologyModel):
    """Auditable benchmark manifest with external source provenance."""

    name: Text
    version: Text
    description: Text
    sources: list[DatasetReference] = Field(min_length=2)
    records: list[LiverBenchRecord] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_manifest(self) -> "LiverBenchDataset":
        """Reject duplicate records/source IDs and degenerate splits."""

        source_ids = [source.id for source in self.sources]
        if len(source_ids) != len(set(source_ids)):
            raise ValueError("LiverBench source IDs must be unique.")
        for required in ("fda_dilirank_2", "fda_dilist"):
            if required not in source_ids:
                raise ValueError(f"LiverBench requires source '{required}'.")

        for field_name in ("id", "ltkbid", "dilist_id"):
            values = [getattr(record, field_name) for record in self.records]
            if len(values) != len(set(values)):
                raise ValueError(f"LiverBench record field '{field_name}' must be unique.")

        for split in ("train", "dev", "heldout"):
            labels = {record.dilist_classification for record in self.records if record.split == split}
            if labels != {0, 1}:
                raise ValueError(f"LiverBench split '{split}' must contain both DILIst classes.")
        return self


class LiverBenchPrediction(BiologyModel):
    """One externally generated binary DILI prediction."""

    record_id: str = Field(min_length=1)
    predicted_label: Literal[0, 1]
    score: Probability | None = Field(
        None,
        description="Optional probability-like score where larger values indicate DILI-positive confidence.",
    )


class LiverBenchPredictions(BiologyModel):
    """Prediction bundle supplied by a model or analysis outside LiverBench."""

    model_name: Text
    model_version: Text | None = None
    predictions: list[LiverBenchPrediction] = Field(min_length=1)

    @model_validator(mode="after")
    def unique_records(self) -> "LiverBenchPredictions":
        ids = [prediction.record_id for prediction in self.predictions]
        if len(ids) != len(set(ids)):
            raise ValueError("LiverBench predictions must contain at most one prediction per record_id.")
        return self


def load_liverbench(path: Path) -> LiverBenchDataset:
    """Load a strict LiverBench manifest."""

    return LiverBenchDataset.model_validate_json(path.read_text())


def dataset_summary(dataset: LiverBenchDataset) -> dict[str, Any]:
    """Return deterministic class/split/cohort counts for audit and CI."""

    split_counts = Counter(record.split for record in dataset.records)
    label_counts = Counter(record.dilist_classification for record in dataset.records)
    cohort_counts = Counter(record.cohort for record in dataset.records)
    return {
        "records": len(dataset.records),
        "splits": dict(sorted(split_counts.items())),
        "labels": {
            "dili_negative": label_counts[0],
            "dili_positive": label_counts[1],
        },
        "cohorts": dict(sorted(cohort_counts.items())),
    }


def build_reference_experiment(record: LiverBenchRecord, dataset: LiverBenchDataset) -> BiologicalExperiment:
    """Represent one benchmark record through the existing biological interface.

    No exposure concentration or measured observation is invented. The two FDA
    labels remain external ReferenceOutcome objects.
    """

    return BiologicalExperiment(
        id=f"liverbench_{record.id}",
        name=f"LiverBench reference: {record.compound_name}",
        organ_model="Liver-on-chip",
        purpose=(
            "Exercise FDA DILI reference provenance through Forma's biological-to-fluidic interface; "
            "this record is not a toxicity prediction or dosing protocol."
        ),
        compartments=[
            BiologicalCompartment(
                id="vascular_compartment",
                role="vascular",
                cell_types=["endothelial cells"],
                fluidic_component_ids=["vascular_chamber", "vascular_channel"],
            ),
            BiologicalCompartment(
                id="hepatic_compartment",
                role="tissue",
                cell_types=["hepatocytes"],
                fluidic_component_ids=["epithelial_chamber", "epithelial_channel"],
                notes="The generic two-channel fixture's epithelial side is assigned the hepatic application role.",
            ),
        ],
        endpoints=[
            BiologicalEndpoint(
                id="dili_reference_label",
                name="External human DILI reference label",
                measurement_type="other",
                description="Reference-only endpoint; no biological response is simulated or measured by Forma.",
                dataset_ref_ids=["fda_dilirank_2", "fda_dilist"],
            )
        ],
        datasets=[source.model_copy(deep=True) for source in dataset.sources],
        reference_outcomes=[
            ReferenceOutcome(
                id="dilirank_reference",
                subject=record.compound_name,
                outcome_type="dili_label",
                value=record.dilirank_concern,
                dataset_ref_id="fda_dilirank_2",
                source_record_id=record.ltkbid,
                notes=f"SeverityClass={record.severity_class}; LabelSection={record.label_section}.",
            ),
            ReferenceOutcome(
                id="dilist_reference",
                subject=record.compound_name,
                outcome_type="dili_label",
                value="DILI-positive" if record.dilist_classification else "DILI-negative",
                dataset_ref_id="fda_dilist",
                source_record_id=str(record.dilist_id),
                notes=f"FDA DILIst route={record.route}.",
            ),
        ],
        limitations=[
            "Reference labels are external ground truth and are not Forma predictions.",
            "No exposure concentration, biological observation, clinical safety conclusion or wet-lab protocol is inferred.",
        ],
    )


def evaluate_interface(
    dataset: LiverBenchDataset,
    project: HardwareIntermediateRepresentation,
) -> dict[str, Any]:
    """Validate every FDA reference record against the existing fluidic fixture."""

    fluidic_issues = (
        validate_fluidic_system(project.fluidic_system)
        if project.fluidic_system is not None
        else []
    )
    failures: list[dict[str, Any]] = []
    for record in dataset.records:
        experiment = build_reference_experiment(record, dataset)
        issues = validate_biological_experiment(experiment, project.fluidic_system)
        if issues:
            failures.append({
                "record_id": record.id,
                "issues": [issue.model_dump(mode="json") for issue in issues],
            })
    return {
        "passed": not fluidic_issues and not failures,
        "cases": len(dataset.records),
        "cases_passed": len(dataset.records) - len(failures),
        "fluidic_issues": [issue.model_dump(mode="json") for issue in fluidic_issues],
        "case_failures": failures,
    }


def _binary_metrics(records: list[LiverBenchRecord], predictions: dict[str, LiverBenchPrediction]) -> dict[str, Any]:
    tp = tn = fp = fn = 0
    for record in records:
        predicted = predictions[record.id].predicted_label
        actual = record.dilist_classification
        if actual == 1 and predicted == 1:
            tp += 1
        elif actual == 0 and predicted == 0:
            tn += 1
        elif actual == 0 and predicted == 1:
            fp += 1
        else:
            fn += 1

    positive_count = tp + fn
    negative_count = tn + fp
    sensitivity = tp / positive_count if positive_count else None
    specificity = tn / negative_count if negative_count else None
    fnr = fn / positive_count if positive_count else None
    accuracy = (tp + tn) / len(records) if records else None
    balanced_accuracy = (
        (sensitivity + specificity) / 2
        if sensitivity is not None and specificity is not None
        else None
    )
    scores_available = all(predictions[record.id].score is not None for record in records)
    auroc = _pairwise_auroc(records, predictions) if scores_available else None
    return {
        "n": len(records),
        "confusion_matrix": {"tp": tp, "tn": tn, "fp": fp, "fn": fn},
        "sensitivity": sensitivity,
        "specificity": specificity,
        "false_negative_rate": fnr,
        "accuracy": accuracy,
        "balanced_accuracy": balanced_accuracy,
        "auroc": auroc,
    }


def _pairwise_auroc(records: list[LiverBenchRecord], predictions: dict[str, LiverBenchPrediction]) -> float | None:
    """Compute AUROC as the positive-vs-negative score concordance probability."""

    positives = [record for record in records if record.dilist_classification == 1]
    negatives = [record for record in records if record.dilist_classification == 0]
    if not positives or not negatives:
        return None
    wins = 0.0
    pairs = 0
    for positive in positives:
        positive_score = predictions[positive.id].score
        assert positive_score is not None
        for negative in negatives:
            negative_score = predictions[negative.id].score
            assert negative_score is not None
            pairs += 1
            if positive_score > negative_score:
                wins += 1
            elif positive_score == negative_score:
                wins += 0.5
    return wins / pairs


def score_predictions(
    dataset: LiverBenchDataset,
    bundle: LiverBenchPredictions,
    split: Literal["train", "dev", "heldout", "all"] = "heldout",
) -> dict[str, Any]:
    """Score externally supplied predictions against DILIst binary ground truth."""

    record_lookup = {record.id: record for record in dataset.records}
    prediction_lookup = {prediction.record_id: prediction for prediction in bundle.predictions}
    unknown = sorted(record_id for record_id in prediction_lookup if record_id not in record_lookup)
    selected = dataset.records if split == "all" else [record for record in dataset.records if record.split == split]
    missing = sorted(record.id for record in selected if record.id not in prediction_lookup)
    complete = not unknown and not missing

    result: dict[str, Any] = {
        "model_name": bundle.model_name,
        "model_version": bundle.model_version,
        "split": split,
        "complete": complete,
        "missing_record_ids": missing,
        "unknown_record_ids": unknown,
        "metrics": None,
        "cohort_accuracy": {},
    }
    if not complete:
        return result

    result["metrics"] = _binary_metrics(selected, prediction_lookup)
    for cohort in sorted({record.cohort for record in selected}):
        cohort_records = [record for record in selected if record.cohort == cohort]
        correct = sum(
            prediction_lookup[record.id].predicted_label == record.dilist_classification
            for record in cohort_records
        )
        result["cohort_accuracy"][cohort] = {
            "n": len(cohort_records),
            "correct": correct,
            "accuracy": correct / len(cohort_records),
        }
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate LiverBench v0, exercise the biology/fluidics interface, and optionally score predictions."
    )
    parser.add_argument("dataset", type=Path, help="LiverBench JSON manifest.")
    parser.add_argument("--project", type=Path, help="Optional Forma Hardware IR with fluidic_system for interface validation.")
    parser.add_argument("--predictions", type=Path, help="Optional externally generated prediction bundle JSON.")
    parser.add_argument("--split", choices=("train", "dev", "heldout", "all"), default="heldout")
    parser.add_argument("--output", type=Path, help="Optional result JSON path.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    dataset = load_liverbench(args.dataset)
    result: dict[str, Any] = {
        "name": dataset.name,
        "version": dataset.version,
        "summary": dataset_summary(dataset),
        "interface": None,
        "prediction_evaluation": None,
        "claims": {
            "reference_labels_are_external": True,
            "toxicity_prediction_generated_by_liverbench": False,
            "clinical_safety_assessment": False,
        },
    }

    passed = True
    if args.project is not None:
        project = HardwareIntermediateRepresentation.model_validate_json(args.project.read_text())
        result["interface"] = evaluate_interface(dataset, project)
        passed = passed and result["interface"]["passed"]

    if args.predictions is not None:
        bundle = LiverBenchPredictions.model_validate_json(args.predictions.read_text())
        result["prediction_evaluation"] = score_predictions(dataset, bundle, args.split)
        passed = passed and result["prediction_evaluation"]["complete"]

    result["passed"] = passed
    payload = json.dumps(result, indent=2, sort_keys=True)
    print(payload)
    if args.output is not None:
        args.output.write_text(payload + "\n")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
