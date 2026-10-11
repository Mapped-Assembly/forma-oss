from __future__ import annotations

import json
import re
from pathlib import Path

from dilimap import datasets
from dilimap.models import ToxPredictor

ROOT = Path(__file__).resolve().parents[1]
LIVERBENCH = ROOT / "examples" / "biology" / "liverbench-v0.json"


def norm(value: object) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value).lower())


def pairwise_auroc(rows: list[dict]) -> float | None:
    positives = [r for r in rows if r["actual"] == 1]
    negatives = [r for r in rows if r["actual"] == 0]
    if not positives or not negatives:
        return None
    wins = 0.0
    pairs = 0
    for p in positives:
        for n in negatives:
            pairs += 1
            if p["risk_score"] > n["risk_score"]:
                wins += 1
            elif p["risk_score"] == n["risk_score"]:
                wins += 0.5
    return wins / pairs


def binary_summary(rows: list[dict]) -> dict:
    tp = sum(r["actual"] == 1 and r["predicted"] == 1 for r in rows)
    tn = sum(r["actual"] == 0 and r["predicted"] == 0 for r in rows)
    fp = sum(r["actual"] == 0 and r["predicted"] == 1 for r in rows)
    fn = sum(r["actual"] == 1 and r["predicted"] == 0 for r in rows)
    p = tp + fn
    n = tn + fp
    sensitivity = tp / p if p else None
    specificity = tn / n if n else None
    return {
        "n": len(rows),
        "positive": p,
        "negative": n,
        "confusion_matrix": {"tp": tp, "tn": tn, "fp": fp, "fn": fn},
        "sensitivity": sensitivity,
        "specificity": specificity,
        "false_negative_rate": fn / p if p else None,
        "accuracy": (tp + tn) / len(rows) if rows else None,
        "balanced_accuracy": (sensitivity + specificity) / 2 if sensitivity is not None and specificity is not None else None,
        "auroc_from_inverse_mos": pairwise_auroc(rows),
    }


def main() -> None:
    manifest = json.loads(LIVERBENCH.read_text())
    liverbench_records = manifest["records"]

    viability = datasets.compound_cell_viability(level="IC10")
    cmax = datasets.compound_Cmax_values()
    validation = datasets.DILImap_validation_data(level="pathways")
    training = datasets.DILImap_training_data(level="pathways")

    viability_names = {norm(idx): idx for idx in viability.index}
    cmax_names = {norm(idx): idx for idx in cmax.index}
    training_names = {norm(v): v for v in training.obs["compound_name"].astype(str).unique()}
    validation_names = {norm(v): v for v in validation.obs["compound_name"].astype(str).unique()}

    coverage = []
    for record in liverbench_records:
        key = norm(record["compound_name"])
        coverage.append({
            "record_id": record["id"],
            "split": record["split"],
            "dilist_classification": record["dilist_classification"],
            "viability": key in viability_names,
            "cmax": key in cmax_names,
            "training_pathways": key in training_names,
            "validation_pathways": key in validation_names,
        })
    print("LIVERBENCH_COVERAGE", json.dumps(coverage, sort_keys=True))

    model = ToxPredictor("v1")
    mos = model.compute_safety_margin(
        validation,
        pert_col="compound_name",
        dose_col="dose_uM",
        cmax_col="Cmax_uM",
        y_pred_col="DILI_probability",
        y_thresh=0.7,
        vmax=300,
        retain_all_cols=True,
    )

    truth = validation.obs[["compound_name", "DILI_label_binary"]].drop_duplicates("compound_name")
    truth_lookup = dict(zip(truth["compound_name"].astype(str), truth["DILI_label_binary"].astype(str)))
    rows = []
    for compound_name, row in mos.iterrows():
        label = truth_lookup.get(str(compound_name))
        if label not in {"DILI", "No DILI"}:
            continue
        margin = float(row["MOS_ToxPredictor"])
        rows.append({
            "compound_name": str(compound_name),
            "actual": 1 if label == "DILI" else 0,
            "predicted": 1 if str(row["Classification"]) == "+" else 0,
            "mos_toxpredictor": margin,
            "risk_score": 1.0 / margin,
            "primary_dili_driver": str(row["Primary_DILI_driver"]),
        })

    result = {
        "source": {
            "dilimap_package_commit": "00d7e4ea232d18109c27cbbec131f09f4ed6245f",
            "public_data_package_top_hash": "155a2b3b63",
            "model_version": "ToxPredictor_v1",
            "prediction_probability_threshold": 0.7,
            "mos_positive_threshold": 80.0,
        },
        "liverbench_overlap": {
            "heldout_total": sum(r["split"] == "heldout" for r in coverage),
            "heldout_viability_and_cmax": [
                r["record_id"] for r in coverage if r["split"] == "heldout" and r["viability"] and r["cmax"]
            ],
            "heldout_pathway_overlap": [
                r["record_id"] for r in coverage if r["split"] == "heldout" and (r["training_pathways"] or r["validation_pathways"])
            ],
        },
        "external_validation": binary_summary(rows),
        "per_compound": rows,
    }
    print("DILIMAP_EXTERNAL_RESULT", json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
