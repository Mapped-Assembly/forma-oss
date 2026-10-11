"""Rebuild the attributed Ewart manifest from three byte-pinned local sources.

Requires openpyxl only for this import step; benchmark execution is offline and
uses no spreadsheet dependency. See docs/ewart-liverchip.md for source URLs.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import xml.etree.ElementTree as ET
from typing import Any

PINS = {
    "article": "48addc159dc30ffb628c4adc4f71dd170f8f3b0b5f4b2f71b5d8fdc7f5719468",
    "correction": "0236ff10c88e6b336faf4b039bc941cf84ef07f16cf05dd303a30f0ff2ae33f7",
    "supplement8": "87cc22d0c1d4508f7e0830df348c52238bdb18d821c8d29cc0751114081509fc",
}
URIS = {
    "article": "https://www.ebi.ac.uk/europepmc/webservices/rest/PMC9727064/fullTextXML",
    "correction": "https://www.ebi.ac.uk/europepmc/webservices/rest/PMC9837064/fullTextXML",
    "supplement8": "https://static-content.springer.com/esm/art%3A10.1038%2Fs43856-022-00209-1/MediaObjects/43856_2022_209_MOESM8_ESM.xlsx",
}
MODELS = ("chip_donor1", "chip_donor2", "chip_both", "spheroid")


def verify_source(path: Path, source: str) -> bytes:
    """Reject changed source bytes rather than silently rebuilding a new version."""
    content = path.read_bytes()
    if hashlib.sha256(content).hexdigest() != PINS[source]:
        raise ValueError(f"SHA256 mismatch for {source}: {path}")
    return content


def table_rows(root: ET.Element, table: str) -> list[list[str]]:
    """Extract displayed cell text in source order, retaining printed bounds."""
    return [["".join(cell.itertext()) for cell in row]
            for row in root.findall(f".//table-wrap[@id='{table}']/table/tbody/tr")]


def build_dataset(article: Path, correction: Path, supplement: Path) -> dict[str, Any]:
    """Extract compound margins, reference counts and individual measurement rows."""
    import openpyxl

    root = ET.fromstring(verify_source(article, "article"))
    verify_source(correction, "correction")
    verify_source(supplement, "supplement8")
    reference, margins = table_rows(root, "Tab1"), table_rows(root, "Tab4")
    if len(reference) != 27 or len(margins) != 27:
        raise ValueError("Expected 27 source compounds.")
    compounds = []
    for row_number, (ref, margin) in enumerate(zip(reference, margins), 1):
        name = margin[0]
        identity_note = None
        if ref[0] != name:
            if row_number != 16 or ref[0] or name != "Olanzapine" or ref[1] != "Yes, matched with Clozapine":
                raise ValueError("Unexpected compound identity mismatch.")
            identity_note = "Table 1 XML name is blank; restored Olanzapine from Table 4 row 16 and the Clozapine matched pair in Tables 1–2."
        compounds.append({"id": name.lower(), "name": name, "garside_rank": int(ref[-1]),
            "reference_label": int(int(ref[-1]) <= 3),
            "reference_locator": f"article:Tab1:row{row_number}",
            "margin_locator": f"article:Tab4:row{row_number}", "identity_note": identity_note,
            **{model: {"raw": value} for model, value in zip(MODELS, margin[1:])}})
    workbook = openpyxl.load_workbook(supplement, data_only=True, read_only=True)
    observations = []
    sheets = {"ALBUMIN": ("albumin", "percent_of_control", "Normalized_Albumin_Levels"),
              "ALT": ("alt", "ng/day/1e6_hepatocytes", "ALT_levels"),
              "Morphology": ("morphology", "morphology_score", "Score")}
    try:
        for sheet, (endpoint, unit, header) in sheets.items():
            rows = list(workbook[sheet].values)
            if rows[0] != ("Compound_Name", "Concentration_Day3", header) or len(rows) != 71:
                raise ValueError(f"Unexpected structure in {sheet}.")
            for row_number, (name, dose, value) in enumerate(rows[1:], 2):
                observations.append({"compound_id": name.lower(), "endpoint": endpoint, "day": 3,
                    "dose_cmax_multiple": float(dose), "value": None if value in {"NA", "NaN"} else float(value), "unit": unit,
                    "source_missing_marker": value if value in {"NA", "NaN"} else None,
                    "source_sheet": sheet, "source_row": row_number})
    finally:
        workbook.close()
    counts = {}
    for key, table in (("published_uncorrected", "Tab5"), ("published_corrected", "Tab6")):
        counts[key] = {model: dict(zip(("tp", "tn", "fp", "fn"), map(int, row[1:5])))
                       for model, row in zip(MODELS, table_rows(root, table))}
    return {"name": "Ewart 2022 Liver-Chip reproduction", "version": "0.1",
        "doi": "10.1038/s43856-022-00209-1", "license": "CC-BY-4.0",
        "attribution": "Ewart et al. (2022), Performance assessment and economic analysis of a human Liver-Chip for predictive toxicology, Communications Medicine. https://doi.org/10.1038/s43856-022-00209-1. CC BY 4.0: https://creativecommons.org/licenses/by/4.0/",
        "changes": ["Transcribed Tables 1 and 4–6 to structured JSON; preserved printed censoring.",
                    "Recovered the blank Olanzapine Table 1 name with an explicit identity note.",
                    "Normalized Supplementary Data 8 into measurement rows; assigned units from Figure 4 and day from workbook headers."],
        "sources": [{"id": key, "uri": URIS[key], "sha256": value} for key, value in PINS.items()],
        "compounds": compounds, "observations": observations, **counts,
        "limitations": [
            "External published experiments, not Forma-generated data or independent validation of a Forma predictor.",
            "Table 4 donor 2 recomputation disagrees with Table 5 by one positive case; the source discrepancy is unresolved.",
            "Paper-convention analysis treats > values as no detected injury; interval-aware results abstain when the bound crosses the threshold.",
            "Complete corrected compound-level margins were not recovered; the 87% sensitivity result is reference-only and was not reproduced.",
            "Corrected thresholds were selected on the study data; the shared two-donor cohort contains 18 drugs, not all 27.",
            "Supplementary Data 8 provides 210 day-3 rows for six drugs without donor or chip identifiers; rows are not assumed to be independent biological replicates.",
            "Dose-response summaries are descriptive only; generalized log-logistic curves and IC50 fits are not reconstructed.",
            "The 2023 correction changes Table 5 spheroid specificity from 100% to 67%; the retrieved article XML already includes this correction."]}


def main() -> None:
    """Build deterministic JSON from explicitly supplied source paths."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("article", type=Path)
    parser.add_argument("correction", type=Path)
    parser.add_argument("supplement8", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    dataset = build_dataset(args.article, args.correction, args.supplement8)
    args.output.write_text(json.dumps(dataset, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
