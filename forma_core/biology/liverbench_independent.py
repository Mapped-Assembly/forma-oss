"""Validation and scoring for independent biological DILI baselines.

This module deliberately does not fetch third-party datasets or run third-party
models. It validates a checked, provenance-rich prediction artifact and recomputes
its metrics deterministically. Source-specific reproduction lives in ``scripts/``.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator

from .models import BiologyModel, Probability, Text


class IndependentBaselineSource(BiologyModel):
    """Pinned provenance for one external biological prediction baseline."""

    name: Text
    citation: Text
    repository: Text
    package_commit: Text
    public_data_package_hash: Text
    model_version: Text
    prediction_probability_threshold: Probability
    mos_positive_threshold: float = Field(gt=0)


class LiverBenchOverlap(BiologyModel):
    """Explicit coverage of the original LiverBench v0 held-out compounds."""

    heldout_total: int = Field(gt=0)
    assay_and_cmax_record_ids: list[str]
    pathway_record_ids: list[str]
    missing_heldout_record_ids: list[str]

    @model_validator(mode="after")
    def heldout_partition_is_consistent(self) -> "LiverBenchOverlap":
        covered = set(self.assay_and_cmax_record_ids)
        missing = set(self.missing_heldout_record_ids)
        if covered & missing:
            raise ValueError("Covered and missing LiverBench held-out IDs must not overlap.")
        if len(covered | missing) != self.heldout_total:
            raise ValueError("Covered + missing LiverBench held-out IDs must equal heldout_total.")
        if not set(self.pathway_record_ids).issubset(covered):
            raise ValueError("Pathway-overlap IDs must also have assay/Cmax coverage.")
        return self


class IndependentPredictionRecord(BiologyModel):
    """One external compound-level classification used for deterministic scoring."""

    compound_name: Text
    actual: Literal[0, 1]
    predicted: Literal[0, 1]
    mos_toxpredictor: float = Field(gt=0)
    risk_score: float = Field(gt=0)
    primary_dili_driver: Text


class IndependentBiologyBaselineArtifact(BiologyModel):
    """Checked output of an external biology-based DILI baseline."""

    name: Text
    version: Text
    source: IndependentBaselineSource
    liverbench_overlap: LiverBenchOverlap
    predictions: list[IndependentPredictionRecord] = Field(min_length=1)
    claims: dict[str, bool]
    limitations: list[Text] = Field(min_length=1)

    @model_validator(mode="after")
    def prediction_compounds_are_unique(self) -> "IndependentBiologyBaselineArtifact":
        names = [record.compound_name.casefold() for record in self.predictions]
        if len(names) != len(set(names)):
            raise ValueError("Independent baseline compound names must be unique.")
        required_false = (
            "liverbench_labels_used_to_generate_predictions",
            "dilirank_used_as_model_feature",
            "forma_generated_biological_measurements",
            "organ_chip_predictive_performance",
        )
        for key in required_false:
            if self.claims.get(key) is not False:
                raise ValueError(f"Independent baseline claim '{key}' must be explicitly false.")
        return self


def load_independent_baseline(path: Path) -> IndependentBiologyBaselineArtifact:
    return IndependentBiologyBaselineArtifact.model_validate_json(path.read_text())


def _pairwise_auroc(records: list[IndependentPredictionRecord]) -> float | None:
    positives = [record for record in records if record.actual == 1]
    negatives = [record for record in records if record.actual == 0]
    if not positives or not negatives:
        return None
    wins = 0.0
    pairs = 0
    for positive in positives:
        for negative in negatives:
            pairs += 1
            if positive.risk_score > negative.risk_score:
                wins += 1
            elif positive.risk_score == negative.risk_score:
                wins += 0.5
    return wins / pairs


def score_independent_baseline(artifact: IndependentBiologyBaselineArtifact) -> dict[str, object]:
    """Recompute binary metrics from the checked compound-level predictions."""

    records = artifact.predictions
    tp = sum(record.actual == 1 and record.predicted == 1 for record in records)
    tn = sum(record.actual == 0 and record.predicted == 0 for record in records)
    fp = sum(record.actual == 0 and record.predicted == 1 for record in records)
    fn = sum(record.actual == 1 and record.predicted == 0 for record in records)
    positives = tp + fn
    negatives = tn + fp
    sensitivity = tp / positives if positives else None
    specificity = tn / negatives if negatives else None
    accuracy = (tp + tn) / len(records)
    balanced_accuracy = (
        (sensitivity + specificity) / 2
        if sensitivity is not None and specificity is not None
        else None
    )
    return {
        "n": len(records),
        "positive": positives,
        "negative": negatives,
        "confusion_matrix": {"tp": tp, "tn": tn, "fp": fp, "fn": fn},
        "sensitivity": sensitivity,
        "specificity": specificity,
        "false_negative_rate": fn / positives if positives else None,
        "accuracy": accuracy,
        "balanced_accuracy": balanced_accuracy,
        "auroc": _pairwise_auroc(records),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate and deterministically score a checked independent-biology baseline artifact."
    )
    parser.add_argument("artifact", type=Path)
    parser.add_argument("--output", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    artifact = load_independent_baseline(args.artifact)
    result = {
        "name": artifact.name,
        "version": artifact.version,
        "source": artifact.source.model_dump(mode="json"),
        "liverbench_overlap": artifact.liverbench_overlap.model_dump(mode="json"),
        "metrics": score_independent_baseline(artifact),
        "claims": artifact.claims,
        "limitations": artifact.limitations,
    }
    payload = json.dumps(result, indent=2, sort_keys=True)
    if args.output is not None:
        args.output.write_text(payload + "\n")
    print(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
