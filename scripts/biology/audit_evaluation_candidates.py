"""Reproduce a preliminary name-overlap audit; never certify dataset independence."""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
from typing import Any
import xml.etree.ElementTree as ET

SOURCE_SHA256 = "88c13554a2898d5b3857143f949ec3316b2da2f1b182207e2ccf92def3e97e90"
SOURCE_URL = "https://www.ebi.ac.uk/europepmc/webservices/rest/PMC5515971/fullTextXML"


def normalize_name(name: str) -> str:
    """Normalize case and outer whitespace only; do not guess salts or synonyms."""
    return name.strip().casefold()


def audit_candidates(article: Path, ewart: Path, liverbench: Path) -> dict[str, Any]:
    """Extract Table 1 identities and flag prior exposure using exact normalized names."""
    content = article.read_bytes()
    if hashlib.sha256(content).hexdigest() != SOURCE_SHA256:
        raise ValueError("Proctor XML SHA256 mismatch; review source changes before rebuilding.")
    sources = {"ewart": json.loads(ewart.read_text(encoding="utf-8")),
               "liverbench": json.loads(liverbench.read_text(encoding="utf-8"))}
    prior: dict[str, list[str]] = {}
    for key, names in (("ewart", [c["name"] for c in sources["ewart"]["compounds"]]),
                       ("liverbench", [c["compound_name"] for c in sources["liverbench"]["records"]])):
        for name in names:
            prior.setdefault(normalize_name(name), []).append(key)
    rows = ET.fromstring(content).findall(".//table-wrap[@id='Tab1']//tbody/tr")
    if len(rows) != 5:
        raise ValueError("Expected five source severity categories.")
    records = []
    for rank, row in enumerate(rows, 1):
        names = [name.strip() for name in "".join(row[1].itertext()).split(",")]
        for name in names:
            matches = prior.get(normalize_name(name), [])
            records.append({"source_name": name, "source_severity_rank": rank,
                "source_binary_label": int(rank <= 3), "source_locator": f"Tab1:row{rank}",
                "prior_name_matches": matches,
                "disposition": "exclude_prior_exposure" if matches else "identity_review_required",
                "chemical_identity_verified": False, "assay_features_verified": False})
    if len(records) != 110 or len({normalize_name(r["source_name"]) for r in records}) != 110:
        raise ValueError("Expected 110 unique source names.")
    counts = Counter(r["disposition"] for r in records)
    return {"name": "LiverChip evaluation source audit", "version": "0.1", "status": "preliminary_not_frozen",
        "candidate_source": {"doi": "10.1007/s00204-017-2002-1", "uri": SOURCE_URL,
            "sha256": SOURCE_SHA256, "license": "CC-BY-4.0",
            "attribution": "Proctor et al. (2017), Utility of spherical human liver microtissues for prediction of clinical drug-induced liver injury. https://doi.org/10.1007/s00204-017-2002-1. https://creativecommons.org/licenses/by/4.0/",
            "changes": "Table 1 names and severity groups transcribed; added preliminary overlap flags. Original spellings retained.",
            "platform": "3D human liver microtissues; not a perfused liver chip"},
        "prior_manifests": [{"name": name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
                            for name, path in (("ewart", ewart), ("liverbench", liverbench))],
        "counts": {"source_compounds": len(records), "name_matched_exclusions": counts["exclude_prior_exposure"],
            "unresolved_candidates": counts["identity_review_required"], "admitted_external_test_compounds": 0},
        "readiness": {"independent_test_ready": False, "chemical_disjointness_verified": False,
            "label_source_independence_verified": False, "assay_compatibility_verified": False,
            "model_training_overlap_verified": False},
        "limitations": ["Name nonmatches do not prove distinct molecules; salts, synonyms and source misspellings require structure-level review.",
            "Benaxoprofen and Sitax(s)entan may correspond to already inspected Ewart compounds; neither is admitted.",
            "All 24 LiverBench and all 27 Ewart compounds are treated as prior exposure, regardless of their original split.",
            "All upstream pretraining, training, tuning and threshold-selection compounds must also be excluded before freezing a test cohort.",
            "The article and aggregate results were inspected for feasibility. This is not a blinded or prospective validation cohort.",
            "Source labels may share literature with development labels; a different publication does not establish label-source independence.",
            "The source groups ranks 1–3 positive and 4–5 negative; rank-4 enzyme elevation cases require a separate sensitivity analysis.",
            "No assay feature extraction, model fitting, or predictive performance evaluation is performed by this audit."],
        "records": records}


def main(argv: list[str] | None = None) -> None:
    """Write the deterministic audit from pinned XML and current prior manifests."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("article", type=Path)
    parser.add_argument("ewart", type=Path)
    parser.add_argument("liverbench", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args(argv)
    if args.output.resolve() in {p.resolve() for p in (args.article, args.ewart, args.liverbench)}:
        parser.error("Output must not overwrite an input.")
    result = audit_candidates(args.article, args.ewart, args.liverbench)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
