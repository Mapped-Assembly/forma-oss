"""Independent molecular baselines for LiverBench.

The baseline in this module uses only PubChem-computed molecular descriptors as
features and DILIst labels from LiverBench train+dev records as supervision. It
never reads DILIrank fields while generating held-out predictions.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

from pydantic import Field, model_validator

from .liverbench import (
    LiverBenchDataset,
    LiverBenchPrediction,
    LiverBenchPredictions,
    load_liverbench,
    score_predictions,
)
from .models import BiologyModel, Text

FEATURE_FIELDS = (
    "molecular_weight",
    "xlogp",
    "hbond_donor_count",
    "hbond_acceptor_count",
    "tpsa",
)
K_NEIGHBORS = 3


class PubChemDescriptorRecord(BiologyModel):
    """Pinned PubChem-computed descriptors for one LiverBench compound."""

    record_id: str = Field(min_length=1)
    compound_name: Text
    pubchem_cid: int = Field(gt=0)
    pubchem_url: Text
    molecular_weight: float = Field(gt=0)
    xlogp: float
    hbond_donor_count: int = Field(ge=0)
    hbond_acceptor_count: int = Field(ge=0)
    tpsa: float = Field(ge=0)


class PubChemDescriptorDataset(BiologyModel):
    """Auditable descriptor manifest used by the independent baseline."""

    name: Text
    version: Text
    description: Text
    source_name: Text
    source_uri: Text
    retrieved_at_utc: Text
    features: list[Text] = Field(min_length=1)
    records: list[PubChemDescriptorRecord] = Field(min_length=1)
    limitations: list[Text] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_manifest(self) -> "PubChemDescriptorDataset":
        if tuple(self.features) != FEATURE_FIELDS:
            raise ValueError(f"PubChem baseline features must be exactly {FEATURE_FIELDS!r}.")
        ids = [record.record_id for record in self.records]
        if len(ids) != len(set(ids)):
            raise ValueError("PubChem descriptor record_id values must be unique.")
        cids = [record.pubchem_cid for record in self.records]
        if len(cids) != len(set(cids)):
            raise ValueError("PubChem descriptor CIDs must be unique for LiverBench v0.")
        return self


def load_pubchem_descriptors(path: Path) -> PubChemDescriptorDataset:
    return PubChemDescriptorDataset.model_validate_json(path.read_text())


def _feature_vector(record: PubChemDescriptorRecord) -> list[float]:
    return [float(getattr(record, field)) for field in FEATURE_FIELDS]


def _standardization(records: list[PubChemDescriptorRecord]) -> tuple[list[float], list[float]]:
    matrix = [_feature_vector(record) for record in records]
    means = [sum(row[column] for row in matrix) / len(matrix) for column in range(len(FEATURE_FIELDS))]
    stds: list[float] = []
    for column, mean in enumerate(means):
        variance = sum((row[column] - mean) ** 2 for row in matrix) / len(matrix)
        std = math.sqrt(variance)
        stds.append(std if std > 0 else 1.0)
    return means, stds


def _zscore(record: PubChemDescriptorRecord, means: list[float], stds: list[float]) -> list[float]:
    return [
        (value - mean) / std
        for value, mean, std in zip(_feature_vector(record), means, stds, strict=True)
    ]


def _distance(left: list[float], right: list[float]) -> float:
    return math.sqrt(sum((a - b) ** 2 for a, b in zip(left, right, strict=True)))


def build_pubchem_knn_baseline(
    dataset: LiverBenchDataset,
    descriptors: PubChemDescriptorDataset,
) -> tuple[LiverBenchPredictions, list[dict[str, Any]]]:
    """Build fixed 3-NN held-out predictions from PubChem descriptors.

    Train and dev labels are the only target labels used during prediction
    generation. Held-out labels are consumed only later by ``score_predictions``.
    """

    descriptor_lookup = {record.record_id: record for record in descriptors.records}
    dataset_ids = {record.id for record in dataset.records}
    descriptor_ids = set(descriptor_lookup)
    if descriptor_ids != dataset_ids:
        missing = sorted(dataset_ids - descriptor_ids)
        unknown = sorted(descriptor_ids - dataset_ids)
        raise ValueError(f"Descriptor coverage must equal LiverBench records; missing={missing}, unknown={unknown}")

    training_records = [record for record in dataset.records if record.split in {"train", "dev"}]
    heldout_records = [record for record in dataset.records if record.split == "heldout"]
    training_descriptors = [descriptor_lookup[record.id] for record in training_records]
    means, stds = _standardization(training_descriptors)
    training_vectors = {
        record.id: _zscore(descriptor_lookup[record.id], means, stds)
        for record in training_records
    }

    predictions: list[LiverBenchPrediction] = []
    details: list[dict[str, Any]] = []
    for record in heldout_records:
        vector = _zscore(descriptor_lookup[record.id], means, stds)
        ranked = sorted(
            (
                (_distance(vector, training_vectors[candidate.id]), candidate.id, candidate.dilist_classification)
                for candidate in training_records
            ),
            key=lambda item: (item[0], item[1]),
        )
        neighbors = ranked[:K_NEIGHBORS]
        score = sum(label for _, _, label in neighbors) / K_NEIGHBORS
        prediction = LiverBenchPrediction(
            record_id=record.id,
            predicted_label=int(score >= 0.5),
            score=score,
        )
        predictions.append(prediction)
        details.append({
            "record_id": record.id,
            "predicted_label": prediction.predicted_label,
            "score": prediction.score,
            "neighbors": [
                {"record_id": neighbor_id, "distance": distance, "label": label}
                for distance, neighbor_id, label in neighbors
            ],
        })

    return (
        LiverBenchPredictions(
            model_name="PubChem molecular descriptor 3-NN baseline",
            model_version="0.1-fixed-k3",
            predictions=predictions,
        ),
        details,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the full-coverage PubChem molecular descriptor baseline on LiverBench held-out records."
    )
    parser.add_argument("dataset", type=Path, help="LiverBench JSON manifest.")
    parser.add_argument("descriptors", type=Path, help="Pinned PubChem descriptor manifest.")
    parser.add_argument("--predictions-output", type=Path)
    parser.add_argument("--output", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    dataset = load_liverbench(args.dataset)
    descriptors = load_pubchem_descriptors(args.descriptors)
    bundle, details = build_pubchem_knn_baseline(dataset, descriptors)
    evaluation = score_predictions(dataset, bundle, "heldout")
    result = {
        "baseline": "pubchem-molecular-knn-v0",
        "method": {
            "features": list(FEATURE_FIELDS),
            "k": K_NEIGHBORS,
            "distance": "euclidean_after_population_zscore",
            "training_splits": ["train", "dev"],
            "evaluation_split": "heldout",
            "uses_dilirank_features": False,
            "uses_heldout_labels_to_generate_predictions": False,
            "biological_assay_features": False,
        },
        "coverage": {
            "descriptor_records": len(descriptors.records),
            "liverbench_records": len(dataset.records),
            "heldout_predictions": len(bundle.predictions),
        },
        "evaluation": evaluation,
        "prediction_details": details,
        "claims": {
            "independent_of_dilirank_features": True,
            "full_liverbench_heldout_coverage": True,
            "biological_assay_baseline": False,
            "organ_chip_predictive_performance": False,
            "clinical_safety_assessment": False,
        },
        "limitations": descriptors.limitations,
    }
    prediction_payload = json.dumps(bundle.model_dump(mode="json"), indent=2, sort_keys=True)
    payload = json.dumps(result, indent=2, sort_keys=True)
    if args.predictions_output is not None:
        args.predictions_output.write_text(prediction_payload + "\n")
    if args.output is not None:
        args.output.write_text(payload + "\n")
    print(payload)
    return 0 if evaluation["complete"] and evaluation["metrics"] is not None else 1


if __name__ == "__main__":
    raise SystemExit(main())
