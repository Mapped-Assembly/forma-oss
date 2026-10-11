"""Transparent reference baselines for LiverBench.

These baselines are intentionally simple and auditable. The DILIrank severity
baseline uses only FDA DILIrank metadata already present in the LiverBench
manifest and is scored against DILIst labels by :mod:`forma_core.biology.liverbench`.

Important: DILIst was constructed in part by augmenting DILIrank, so this is a
reference/sanity baseline, not independent biological validation and not an
organ-on-chip toxicity model.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Literal

from .liverbench import (
    LiverBenchDataset,
    LiverBenchPrediction,
    LiverBenchPredictions,
    load_liverbench,
    score_predictions,
)

BaselineName = Literal["dilirank-severity-v0", "constant-negative-v0"]

# Fixed a priori for v0. No train/dev/held-out DILIst labels are consulted when
# generating a prediction for a record.
DILIRANK_SEVERITY_POSITIVE_THRESHOLD = 5
DILIRANK_MAX_SEVERITY_CLASS = 8


def build_dilirank_severity_baseline(dataset: LiverBenchDataset) -> LiverBenchPredictions:
    """Map FDA DILIrank SeverityClass to a binary DILIst prediction.

    Score is ``SeverityClass / 8`` and the binary label is positive for severity
    class >= 5. The mapping is deliberately fixed and deterministic; it is not
    fit to LiverBench labels.
    """

    return LiverBenchPredictions(
        model_name="FDA DILIrank severity reference baseline",
        model_version="0.1-threshold-5",
        predictions=[
            LiverBenchPrediction(
                record_id=record.id,
                predicted_label=int(record.severity_class >= DILIRANK_SEVERITY_POSITIVE_THRESHOLD),
                score=record.severity_class / DILIRANK_MAX_SEVERITY_CLASS,
            )
            for record in dataset.records
        ],
    )


def build_constant_negative_baseline(dataset: LiverBenchDataset) -> LiverBenchPredictions:
    """Return a no-skill all-negative floor with tied scores for AUROC=0.5."""

    return LiverBenchPredictions(
        model_name="Constant negative no-skill baseline",
        model_version="0.1",
        predictions=[
            LiverBenchPrediction(record_id=record.id, predicted_label=0, score=0.0)
            for record in dataset.records
        ],
    )


def build_baseline(dataset: LiverBenchDataset, name: BaselineName) -> LiverBenchPredictions:
    """Build one named deterministic LiverBench baseline."""

    if name == "dilirank-severity-v0":
        return build_dilirank_severity_baseline(dataset)
    if name == "constant-negative-v0":
        return build_constant_negative_baseline(dataset)
    raise ValueError(f"Unknown LiverBench baseline: {name}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Generate and score transparent reference baselines for LiverBench."
    )
    parser.add_argument("dataset", type=Path, help="LiverBench JSON manifest.")
    parser.add_argument(
        "--baseline",
        choices=("dilirank-severity-v0", "constant-negative-v0"),
        default="dilirank-severity-v0",
    )
    parser.add_argument(
        "--split",
        choices=("train", "dev", "heldout", "all"),
        default="heldout",
        help="Split used for the reported evaluation; predictions are generated for all records.",
    )
    parser.add_argument("--predictions-output", type=Path, help="Optional prediction-bundle JSON path.")
    parser.add_argument("--output", type=Path, help="Optional evaluation-result JSON path.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    dataset = load_liverbench(args.dataset)
    bundle = build_baseline(dataset, args.baseline)
    evaluation = score_predictions(dataset, bundle, args.split)

    result = {
        "baseline": args.baseline,
        "prediction_generation": {
            "uses_dilist_labels": False,
            "trained_parameters": False,
            "independent_biological_validation": False,
        },
        "evaluation": evaluation,
        "limitations": [
            "DILIst was constructed in part by augmenting DILIrank, so this reference baseline is not an independent validation set.",
            "DILIrank SeverityClass is external human DILI curation, not a measurement or prediction produced by Forma or an organ-on-chip model.",
            "The baseline exists to establish a transparent floor before adding independent biological-response models.",
        ],
    }

    prediction_payload = json.dumps(bundle.model_dump(mode="json"), indent=2, sort_keys=True)
    result_payload = json.dumps(result, indent=2, sort_keys=True)
    if args.predictions_output is not None:
        args.predictions_output.write_text(prediction_payload + "\n")
    if args.output is not None:
        args.output.write_text(result_payload + "\n")
    print(result_payload)
    return 0 if evaluation["complete"] and evaluation["metrics"] is not None else 1


if __name__ == "__main__":
    raise SystemExit(main())
