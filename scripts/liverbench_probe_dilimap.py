from __future__ import annotations

import json
import re
from pathlib import Path

from dilimap import datasets

ROOT = Path(__file__).resolve().parents[1]
LIVERBENCH = ROOT / "examples" / "biology" / "liverbench-v0.json"


def norm(value: object) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value).lower())


def main() -> None:
    manifest = json.loads(LIVERBENCH.read_text())
    targets = {norm(row["compound_name"]): row["compound_name"] for row in manifest["records"]}
    print("LIVERBENCH_TARGETS", sorted(targets.values()))

    viability = datasets.compound_cell_viability(level="IC10")
    print("VIABILITY_SHAPE", viability.shape)
    print("VIABILITY_COLUMNS", list(viability.columns))
    print("VIABILITY_HEAD")
    print(viability.head(10).to_string(index=False))

    for column in viability.columns:
        values = viability[column].astype(str)
        matches = viability[values.map(norm).isin(targets)]
        if not matches.empty:
            print("VIABILITY_MATCH_COLUMN", column, "N", len(matches))
            print(matches.to_string(index=False))

    cmax = datasets.compound_Cmax_values()
    print("CMAX_SHAPE", cmax.shape)
    print("CMAX_COLUMNS", list(cmax.columns))
    print("CMAX_HEAD")
    print(cmax.head(10).to_string(index=False))
    for column in cmax.columns:
        values = cmax[column].astype(str)
        matches = cmax[values.map(norm).isin(targets)]
        if not matches.empty:
            print("CMAX_MATCH_COLUMN", column, "N", len(matches))
            print(matches.to_string(index=False))

    validation = datasets.DILImap_validation_data(level="pathways")
    print("VALIDATION_SHAPE", validation.shape)
    print("VALIDATION_OBS_COLUMNS", list(validation.obs.columns))
    print("VALIDATION_VAR_HEAD", list(validation.var_names[:10]))
    print("VALIDATION_OBS_HEAD")
    print(validation.obs.head(10).to_string())
    for column in validation.obs.columns:
        values = validation.obs[column].astype(str)
        matches = validation.obs[values.map(norm).isin(targets)]
        if not matches.empty:
            print("VALIDATION_MATCH_COLUMN", column, "N", len(matches))
            print(matches.to_string())

    training = datasets.DILImap_training_data(level="pathways")
    print("TRAINING_SHAPE", training.shape)
    print("TRAINING_OBS_COLUMNS", list(training.obs.columns))
    for column in training.obs.columns:
        values = training.obs[column].astype(str)
        matches = training.obs[values.map(norm).isin(targets)]
        if not matches.empty:
            print("TRAINING_MATCH_COLUMN", column, "N", len(matches))
            print(matches.to_string())


if __name__ == "__main__":
    main()
