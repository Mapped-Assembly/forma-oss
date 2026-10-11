"""Reproduce published Ewart 2022 Liver-Chip summary results, without model training.

The paper-convention analysis treats a reported '>' margin as no detected injury.
A separate interval-aware audit abstains when that bound straddles the threshold.
Neither analysis is prospective validation of a Forma toxicity predictor.
"""

from __future__ import annotations

import argparse
import json
import math
import re
from collections import defaultdict
from pathlib import Path
from statistics import mean, stdev
from typing import Any, Literal

from pydantic import Field, model_validator

from .models import BiologyModel, NonNegative, Text

Mode = Literal["paper_convention", "interval_aware"]
MODEL_FIELDS = ("chip_donor1", "chip_donor2", "chip_both", "spheroid")
THRESHOLD = 50.0


class Margin(BiologyModel):
    """A printed MOS value with its original censoring symbol preserved."""

    raw: Text

    @model_validator(mode="after")
    def valid_margin(self) -> Margin:
        """Require a recognized nonnegative number, bound or missing marker."""
        parse_margin(self.raw)
        return self


def parse_margin(raw: str) -> tuple[str, float | None]:
    """Parse printed numeric bounds without converting censoring into exact values."""
    cleaned = raw.replace(",", "").replace(" ", "").replace("\u00a0", "")
    if cleaned in {"-", "–", "—"}:
        return "missing", None
    if not re.fullmatch(r"[<>]?(?:\d+(?:\.\d*)?|\.\d+)", cleaned):
        raise ValueError(f"Unrecognized margin: {raw!r}")
    kind = {">": "gt", "<": "lt"}.get(cleaned[0], "exact")
    number = float(cleaned.lstrip("<>"))
    if not math.isfinite(number) or number < 0 or (kind == "lt" and number == 0):
        raise ValueError("Margin must describe a finite nonnegative range.")
    return kind, number


def classify_margin(margin: Margin, mode: Mode) -> int | None:
    """Classify with the paper's threshold, optionally retaining interval uncertainty."""
    if mode not in {"paper_convention", "interval_aware"}:
        raise ValueError(f"Unknown analysis mode: {mode}")
    kind, value = parse_margin(margin.raw)
    if kind == "missing":
        return None
    assert value is not None
    if kind == "exact":
        return int(value <= THRESHOLD)
    if kind == "gt":
        return 0 if mode == "paper_convention" or value >= THRESHOLD else None
    return 1 if value <= THRESHOLD else None


class Compound(BiologyModel):
    """One published compound, reference severity and four printed MOS entries."""

    id: Text
    name: Text
    garside_rank: int = Field(ge=1, le=5)
    reference_label: Literal[0, 1]
    reference_locator: Text
    margin_locator: Text
    identity_note: str | None = None
    chip_donor1: Margin
    chip_donor2: Margin
    chip_both: Margin
    spheroid: Margin

    @model_validator(mode="after")
    def reference_consistency(self) -> Compound:
        """Preserve the study's rank 1–3 positive versus rank 4–5 negative grouping."""
        if self.reference_label != int(self.garside_rank <= 3):
            raise ValueError("Reference label disagrees with the published severity grouping.")
        return self


class Observation(BiologyModel):
    """One source workbook row; donor and chip identities are not supplied there."""

    compound_id: Text
    endpoint: Literal["albumin", "alt", "morphology"]
    day: Literal[3]
    dose_cmax_multiple: NonNegative
    value: float | None
    source_missing_marker: Literal["NA", "NaN"] | None = None
    unit: Literal["percent_of_control", "ng/day/1e6_hepatocytes", "morphology_score"]
    source_sheet: Text
    source_row: int = Field(ge=2)

    @model_validator(mode="after")
    def endpoint_units(self) -> Observation:
        """Reject incompatible units while retaining measured numerical values."""
        if (self.value is None) != (self.source_missing_marker is not None):
            raise ValueError("Missing values must retain the source missing marker.")
        expected = {"albumin": "percent_of_control", "alt": "ng/day/1e6_hepatocytes",
                    "morphology": "morphology_score"}
        if self.unit != expected[self.endpoint]:
            raise ValueError("Observation unit does not match endpoint.")
        return self


class Source(BiologyModel):
    """Source identity for rebuilding a derived, attributed data manifest."""

    id: Text
    uri: Text
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")


class Counts(BiologyModel):
    """Binary outcome counts transcribed from a published summary table."""

    tp: int = Field(ge=0)
    tn: int = Field(ge=0)
    fp: int = Field(ge=0)
    fn: int = Field(ge=0)


class EwartDataset(BiologyModel):
    """Versioned external reproduction dataset, separate from LiverBench v0."""

    name: Text
    version: Literal["0.1"]
    doi: Literal["10.1038/s43856-022-00209-1"]
    license: Literal["CC-BY-4.0"]
    attribution: Text
    changes: list[Text]
    sources: list[Source]
    compounds: list[Compound] = Field(min_length=1)
    observations: list[Observation]
    published_uncorrected: dict[str, Counts]
    published_corrected: dict[str, Counts]
    limitations: list[Text]

    @model_validator(mode="after")
    def valid_relationships(self) -> EwartDataset:
        """Reject duplicate or unknown identities and incomplete model references."""
        ids = [c.id for c in self.compounds]
        if len(ids) != len(set(ids)):
            raise ValueError("Compound IDs must be unique.")
        if len({s.id for s in self.sources}) != len(self.sources):
            raise ValueError("Source IDs must be unique.")
        if {s.id for s in self.sources} != {"article", "correction", "supplement8"}:
            raise ValueError("Expected article, correction and supplement8 provenance.")
        locations = [(o.source_sheet, o.source_row) for o in self.observations]
        if len(locations) != len(set(locations)):
            raise ValueError("Source measurement rows must not be duplicated.")
        if any(o.compound_id not in ids for o in self.observations):
            raise ValueError("Observation references an unknown compound.")
        for reference in (self.published_uncorrected, self.published_corrected):
            if set(reference) != set(MODEL_FIELDS):
                raise ValueError("Expected all four published model references.")
        return self


def load_dataset(path: Path) -> EwartDataset:
    """Load and validate a frozen derived source manifest."""
    return EwartDataset.model_validate_json(path.read_text(encoding="utf-8"))


def predict_margins(dataset: EwartDataset, model: str, mode: Mode) -> list[dict[str, Any]]:
    """Generate decisions exclusively from printed MOS values, without labels."""
    if model not in MODEL_FIELDS:
        raise ValueError(f"Unknown model: {model}")
    rows = []
    for compound in dataset.compounds:
        margin = getattr(compound, model)
        kind, _ = parse_margin(margin.raw)
        predicted = classify_margin(margin, mode)
        rows.append({"compound_id": compound.id, "raw_margin": margin.raw,
                     "predicted_label": predicted, "censoring": kind,
                     "reason": "not_tested" if kind == "missing" else (
                         "bound_straddles_threshold" if predicted is None else "classified")})
    return rows


def summarize_model(dataset: EwartDataset, model: str, mode: Mode) -> dict[str, Any]:
    """Compare computed decisions to reference labels and the published counts."""
    predictions = predict_margins(dataset, model, mode)
    truth = {c.id: c.reference_label for c in dataset.compounds}
    counts = {"tp": 0, "tn": 0, "fp": 0, "fn": 0}
    for row in predictions:
        predicted = row["predicted_label"]
        if predicted is not None:
            key = (("tn", "fp"), ("fn", "tp"))[truth[row["compound_id"]]][predicted]
            counts[key] += 1
    positive, negative = counts["tp"] + counts["fn"], counts["tn"] + counts["fp"]
    n = positive + negative
    expected = dataset.published_uncorrected[model].model_dump()
    return {
        "mode": mode, "threshold": THRESHOLD, "confusion_matrix": counts,
        "n_classified": n, "n_not_tested": sum(r["reason"] == "not_tested" for r in predictions),
        "n_indeterminate": sum(r["reason"] == "bound_straddles_threshold" for r in predictions),
        "sensitivity": counts["tp"] / positive if positive else None,
        "specificity": counts["tn"] / negative if negative else None,
        "metric_population": "classified records only; indeterminate and untested excluded",
        "published_table5_counts": expected,
        "matches_published_counts": counts == expected if mode == "paper_convention" else None,
        "count_deltas": {k: counts[k] - expected[k] for k in counts} if mode == "paper_convention" else None,
        "decisions": predictions,
    }


def summarize_observations(dataset: EwartDataset) -> list[dict[str, Any]]:
    """Compute descriptive means and sample SEM, without fitting dose-response curves."""
    groups: dict[tuple[str, str, float], list[Observation]] = defaultdict(list)
    for observation in dataset.observations:
        groups[(observation.compound_id, observation.endpoint, observation.dose_cmax_multiple)].append(observation)
    output = []
    for (compound, endpoint, dose), observations in sorted(groups.items()):
        values = [o.value for o in observations if o.value is not None]
        output.append({"compound_id": compound, "endpoint": endpoint, "dose_cmax_multiple": dose,
                       "day": 3, "unit": observations[0].unit, "n": len(values), "n_missing": len(observations) - len(values),
                       "mean": mean(values) if values else None,
                       "sem": stdev(values) / math.sqrt(len(values)) if len(values) > 1 else None,
                       "source_rows": [o.source_row for o in observations],
                       "source_sheet": observations[0].source_sheet})
    return output


def build_report(dataset: EwartDataset) -> dict[str, Any]:
    """Produce an audit that exposes mismatches and distinguishes reported-only results."""
    models = {model: summarize_model(dataset, model, "paper_convention") for model in MODEL_FIELDS}
    mismatches = [model for model, result in models.items() if not result["matches_published_counts"]]
    return {
        "dataset": {"name": dataset.name, "version": dataset.version, "doi": dataset.doi,
                    "compounds": len(dataset.compounds), "observation_rows": len(dataset.observations),
                    "measured_values": sum(o.value is not None for o in dataset.observations),
                    "missing_values": sum(o.value is None for o in dataset.observations),
                    "observed_compounds": len({o.compound_id for o in dataset.observations})},
        "sources": [source.model_dump() for source in dataset.sources],
        "uncorrected_reproduction": models,
        "interval_aware_audit": {model: summarize_model(dataset, model, "interval_aware") for model in MODEL_FIELDS},
        "all_uncorrected_counts_match": not mismatches,
        "mismatched_models": mismatches,
        "corrected_analysis": {"status": "not_reproduced", "reported_table6_counts": {
            name: counts.model_dump() for name, counts in dataset.published_corrected.items()},
            "reason": "Complete compound-level corrected margins were not recovered; aggregate counts are reference only.",
            "chip_threshold_reported": 375, "threshold_selected_on_study_data": True},
        "dose_response_summary": summarize_observations(dataset),
        "claims": {"external_experimental_data": True, "raw_curve_refit": False,
                   "forma_generated_measurements": False, "independent_predictor_validation": False,
                   "new_model_trained": False, "clinical_safety_assessment": False},
        "limitations": dataset.limitations,
    }


def main(argv: list[str] | None = None) -> int:
    """Run an offline audit; an optional strict gate fails on any published-count mismatch."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dataset", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--require-all-uncorrected-matches", action="store_true")
    args = parser.parse_args(argv)
    report = build_report(load_dataset(args.dataset))
    payload = json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n"
    if args.output:
        args.output.write_text(payload, encoding="utf-8")
    print(payload, end="")
    return 2 if args.require_all_uncorrected_matches and not report["all_uncorrected_counts_match"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
