from __future__ import annotations

import json
import re
from pathlib import Path

from dilimap import datasets

ROOT = Path(__file__).resolve().parents[1]
LIVERBENCH = ROOT / "examples" / "biology" / "liverbench-v0.json"


def norm(value: object) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value).lower())


def index_overlap(frame, records, label: str) -> None:
    by_norm = {norm(idx): idx for idx in frame.index}
    matched = []
    missing = []
    for record in records:
        key = norm(record["compound_name"])
        if key not in by_norm:
            missing.append(record["id"])
            continue
        source_name = by_norm[key]
        row = frame.loc[source_name]
        matched.append((record, source_name, row))

    print(label + "_INDEX_NAME", frame.index.name)
    print(label + "_OVERLAP_N", len(matched), "OF", len(records))
    print(label + "_MISSING", missing)
    for record, source_name, row in matched:
        payload = row.to_dict() if hasattr(row, "to_dict") else {"value": row}
        print(
            label + "_MATCH",
            json.dumps(
                {
                    "record_id": record["id"],
                    "compound_name": record["compound_name"],
                    "split": record["split"],
                    "dilist_classification": record["dilist_classification"],
                    "source_name": str(source_name),
                    "values": payload,
                },
                sort_keys=True,
                default=str,
            ),
        )


def obs_overlap(adata, records, label: str) -> None:
    if "compound_name" not in adata.obs.columns:
        print(label + "_NO_COMPOUND_NAME")
        return
    names = {norm(value): value for value in adata.obs["compound_name"].astype(str).unique()}
    matched = []
    for record in records:
        key = norm(record["compound_name"])
        if key in names:
            matched.append((record["id"], record["split"], record["dilist_classification"], names[key]))
    print(label + "_COMPOUND_OVERLAP_N", len(matched), "OF", len(records))
    print(label + "_COMPOUND_OVERLAP", json.dumps(matched, sort_keys=True))


def main() -> None:
    manifest = json.loads(LIVERBENCH.read_text())
    records = manifest["records"]
    print("LIVERBENCH_TARGETS", [row["compound_name"] for row in records])

    viability = datasets.compound_cell_viability(level="IC10")
    print("VIABILITY_SHAPE", viability.shape)
    print("VIABILITY_COLUMNS", list(viability.columns))
    index_overlap(viability, records, "VIABILITY")

    cmax = datasets.compound_Cmax_values()
    print("CMAX_SHAPE", cmax.shape)
    print("CMAX_COLUMNS", list(cmax.columns))
    index_overlap(cmax, records, "CMAX")

    validation = datasets.DILImap_validation_data(level="pathways")
    print("VALIDATION_SHAPE", validation.shape)
    print("VALIDATION_OBS_COLUMNS", list(validation.obs.columns))
    obs_overlap(validation, records, "VALIDATION")

    training = datasets.DILImap_training_data(level="pathways")
    print("TRAINING_SHAPE", training.shape)
    print("TRAINING_OBS_COLUMNS", list(training.obs.columns))
    obs_overlap(training, records, "TRAINING")


if __name__ == "__main__":
    main()
