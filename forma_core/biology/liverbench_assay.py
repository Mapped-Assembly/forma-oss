"""Optional local IC10/Cmax assay baseline with explicit missing-data abstention.

No third-party data or model weights are distributed or downloaded. DILImap's
public CSV column layout is supported; users must have rights to their inputs.
The cytotoxicity-only rule is not the complete ToxPredictor model.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from pathlib import Path
from typing import Any

from pydantic import Field, model_validator

from .liverbench import (
    BenchmarkSplit,
    LiverBenchDataset,
    LiverBenchPrediction,
    LiverBenchPredictions,
    load_liverbench,
    score_predictions,
)
from .models import BiologyModel, Positive, Text

MARGIN_THRESHOLD = 80.0
METHOD_REFERENCE = (
    "https://github.com/Cellarity/DILImap/blob/"
    "00d7e4ea232d18109c27cbbec131f09f4ed6245f/dilimap/models.py"
)


class AssayRecord(BiologyModel):
    """One exact-name join, retaining missing source rows and missing estimates."""

    record_id: Text
    compound_name: Text
    viability_source_name: Text | None = None
    cmax_source_name: Text | None = None
    ic10_um: Positive | None = None
    cmax_um: Positive | None = None

    @model_validator(mode="after")
    def consistent_sources(self) -> AssayRecord:
        """Reject values without a source row or a mismatched compound identity."""
        for name, value in (
            (self.viability_source_name, self.ic10_um),
            (self.cmax_source_name, self.cmax_um),
        ):
            if value is not None and name is None:
                raise ValueError("Assay values require a named source row.")
            if name is not None and _identity(name) != _identity(self.compound_name):
                raise ValueError("Assay source name must match the compound exactly, ignoring case/space.")
        return self


class AssaySource(BiologyModel):
    """Content digest and user-supplied provenance for a local CSV input."""

    name: Text
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    source_uri: Text


class AssayDataset(BiologyModel):
    """Explicit coverage manifest; every benchmark compound must be represented."""

    sources: list[AssaySource] = Field(min_length=2, max_length=2)
    records: list[AssayRecord] = Field(min_length=1)

    @model_validator(mode="after")
    def unique_records(self) -> AssayDataset:
        """Reject duplicate benchmark IDs and duplicate source identities."""
        ids = [record.record_id for record in self.records]
        if len(ids) != len(set(ids)):
            raise ValueError("Assay record IDs must be unique.")
        if {source.name for source in self.sources} != {"viability", "cmax"}:
            raise ValueError("Assay sources must contain viability and cmax exactly once.")
        return self


def _identity(name: str) -> str:
    """Normalize only outer whitespace and case; never infer salt or synonym matches."""
    return name.strip().casefold()


def _read_csv(path: Path, key: str, value_column: str) -> tuple[dict[str, dict[str, str]], str]:
    """Read exact source columns and reject ambiguous compound rows."""
    payload = path.read_bytes()
    reader = csv.DictReader(payload.decode("utf-8-sig").splitlines())
    if not {key, value_column}.issubset(reader.fieldnames or []):
        raise ValueError(f"{path.name} requires columns {key!r} and {value_column!r}.")
    rows: dict[str, dict[str, str]] = {}
    for row in reader:
        if row.get(key) is None or row.get(value_column) is None:
            raise ValueError(f"Malformed CSV row in {path.name}.")
        identity = _identity(row[key])
        if not identity or identity in rows:
            raise ValueError(f"Empty or duplicate compound name in {path.name}: {identity!r}.")
        rows[identity] = row
    return rows, hashlib.sha256(payload).hexdigest()


def _optional_positive(value: str | None) -> float | None:
    """Preserve explicit missing estimates; reject nonfinite/nonpositive measurements."""
    if value is None or value.strip().casefold() in {"", "nan", "na", "n/a"}:
        return None
    number = float(value)
    if not math.isfinite(number) or number <= 0:
        raise ValueError("IC10 and Cmax estimates must be finite and positive when supplied.")
    return number


def load_assay_csvs(
    dataset: LiverBenchDataset,
    viability_path: Path,
    cmax_path: Path,
    *,
    source_uri: str,
) -> AssayDataset:
    """Join user-provided IC10/Cmax CSVs without reading any FDA label fields.

    Expected columns: Compound, IC10_uM; LIBRARY CMPDS, Cmax_median. Both
    concentration columns must be in micromolar. Unmatched names stay missing.
    """
    viability, viability_hash = _read_csv(viability_path, "Compound", "IC10_uM")
    cmax, cmax_hash = _read_csv(cmax_path, "LIBRARY CMPDS", "Cmax_median")
    rows: list[AssayRecord] = []
    for record in dataset.records:
        name = _identity(record.compound_name)
        assay_row, cmax_row = viability.get(name, {}), cmax.get(name, {})
        rows.append(AssayRecord(
            record_id=record.id,
            compound_name=record.compound_name,
            viability_source_name=assay_row.get("Compound"),
            cmax_source_name=cmax_row.get("LIBRARY CMPDS"),
            ic10_um=_optional_positive(assay_row.get("IC10_uM")),
            cmax_um=_optional_positive(cmax_row.get("Cmax_median")),
        ))
    return AssayDataset(sources=[
        AssaySource(name="viability", sha256=viability_hash, source_uri=source_uri),
        AssaySource(name="cmax", sha256=cmax_hash, source_uri=source_uri),
    ], records=rows)


def build_assay_baseline(
    dataset: LiverBenchDataset,
    assays: AssayDataset,
    split: BenchmarkSplit = "heldout",
) -> tuple[LiverBenchPredictions | None, list[dict[str, Any]]]:
    """Apply a fixed IC10/Cmax < 80 rule, abstaining on every unavailable input.

    No fitting, threshold selection, FDA labels, or DILIrank features are used.
    A missing IC10 is not interpreted as a negative result or an infinite margin.
    """
    lookup = {record.record_id: record for record in assays.records}
    if set(lookup) != {record.id for record in dataset.records}:
        raise ValueError("Assay manifest must explicitly cover every benchmark ID, including missing data.")
    predictions: list[LiverBenchPrediction] = []
    details: list[dict[str, Any]] = []
    for record in dataset.records:
        assay = lookup[record.id]
        if _identity(assay.compound_name) != _identity(record.compound_name):
            raise ValueError(f"Assay compound identity mismatch for {record.id}.")
        if record.split != split:
            continue
        missing = []
        for source, value, label in (
            (assay.viability_source_name, assay.ic10_um, "ic10"),
            (assay.cmax_source_name, assay.cmax_um, "cmax"),
        ):
            if source is None:
                missing.append(f"missing_{label}_source_row")
            elif value is None:
                missing.append(f"missing_{label}_estimate")
        detail: dict[str, Any] = {"record_id": record.id, "abstained": bool(missing), "reasons": missing}
        if not missing:
            assert assay.ic10_um is not None and assay.cmax_um is not None
            margin = assay.ic10_um / assay.cmax_um
            if not math.isfinite(margin) or margin <= 0:
                raise ValueError("IC10/Cmax ratio is outside the finite positive range.")
            # Monotone ranking score only; not a calibrated DILI probability.
            score = 1.0 / (1.0 + margin)
            prediction = LiverBenchPrediction(
                record_id=record.id, predicted_label=int(margin < MARGIN_THRESHOLD), score=score,
            )
            predictions.append(prediction)
            detail.update(margin=margin, predicted_label=prediction.predicted_label, score=score)
        details.append(detail)
    bundle = LiverBenchPredictions(
        model_name="External cytotoxicity IC10/Cmax baseline",
        model_version="0.1-fixed-margin80-abstain",
        predictions=predictions,
    ) if predictions else None
    return bundle, details


def evaluate_assay_baseline(
    dataset: LiverBenchDataset, assays: AssayDataset, split: BenchmarkSplit = "heldout",
) -> dict[str, Any]:
    """Audit coverage and score only complete splits through the existing strict scorer."""
    bundle, details = build_assay_baseline(dataset, assays, split)
    missing = [row["record_id"] for row in details if row["abstained"]]
    evaluation = score_predictions(dataset, bundle, split) if bundle else {
        "split": split, "complete": False, "metrics": None,
        "missing_record_ids": missing, "unknown_record_ids": [], "cohort_accuracy": {},
    }
    return {
        "baseline": "external-cytotoxicity-margin-v0",
        "sources": [source.model_dump() for source in assays.sources],
        "method": {"rule": "IC10_uM / Cmax_uM < 80", "threshold": MARGIN_THRESHOLD,
                   "reference": METHOD_REFERENCE, "fitted_parameters": 0,
                   "missing_estimates": "abstain", "score_is_calibrated_probability": False},
        "coverage": {"selected_records": len(details), "predicted_records": len(details) - len(missing),
                     "abstained_records": len(missing), "missing_record_ids": missing},
        "predictions": bundle.model_dump(mode="json") if bundle else None,
        "prediction_details": details,
        "evaluation": evaluation,
        "claims": {"uses_dilirank_features": False, "uses_labels_for_prediction": False,
                   "complete_toxpredictor_reproduction": False, "independent_validation": False,
                   "organ_chip_predictive_performance": False, "clinical_safety_assessment": False},
    }


def main(argv: list[str] | None = None) -> int:
    """Run an offline audit; optionally require full coverage for a scoring gate."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dataset", type=Path)
    parser.add_argument("viability_csv", type=Path)
    parser.add_argument("cmax_csv", type=Path)
    parser.add_argument("--source-uri", required=True, help="Provenance URI for your licensed inputs.")
    parser.add_argument("--split", choices=("train", "dev", "heldout"), default="heldout")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--require-complete", action="store_true")
    args = parser.parse_args(argv)
    dataset = load_liverbench(args.dataset)
    assays = load_assay_csvs(dataset, args.viability_csv, args.cmax_csv, source_uri=args.source_uri)
    result = evaluate_assay_baseline(dataset, assays, args.split)
    payload = json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n"
    if args.output:
        args.output.write_text(payload, encoding="utf-8")
    print(payload, end="")
    return 2 if args.require_complete and not result["evaluation"]["complete"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
