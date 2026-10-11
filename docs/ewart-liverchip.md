# Ewart 2022 Liver-Chip reproduction

This offline benchmark audits published experimental results from Ewart et al.,
*Performance assessment and economic analysis of a human Liver-Chip for predictive
toxicology*, Communications Medicine (2022),
[doi:10.1038/s43856-022-00209-1](https://doi.org/10.1038/s43856-022-00209-1).
It is separate from LiverBench v0 and does not train or validate a Forma predictor.

## Reproduced results and unresolved discrepancy

The dataset retains 27 compounds from Tables 1 and 4, severity ranks and printed
margin-of-safety (MOS) values. Ranks 1–3 are reference positives; ranks 4–5 are
reference negatives. Exact MOS values at or below 50 are classified positive.
The `paper_convention` analysis treats `>` entries as no detected injury and
therefore negative. Untested entries are excluded.

| Table 4 analysis | TP | TN | FP | FN | Sensitivity | Specificity | Matches Table 5? |
|---|---:|---:|---:|---:|---:|---:|---|
| Chip donor 1 | 16 | 5 | 0 | 6 | 72.73% | 100% | Yes |
| Chip donor 2 | 10 | 3 | 0 | 5 | 66.67% | 100% | **No** |
| Chip both donors | 12 | 3 | 0 | 3 | 80% | 100% | Yes |
| Spheroid | 8 | 2 | 1 | 11 | 42.11% | 66.67% | Yes |

Table 5 reports donor-2 TP=9 and FN=6. Recomputing the printed Table 4 values
produces TP=10 and FN=5. The report exposes the disagreement without changing
source values or guessing which row is wrong. The
[2023 correction](https://pmc.ncbi.nlm.nih.gov/articles/PMC9837064/) changes
Table 5 spheroid specificity from 100% to 67%; the pinned article XML already
contains the correction.

A `>` bound below 50 does **not** logically establish a negative classification.
The separate `interval_aware_audit` abstains on those entries. For both donors,
this leaves 14 classified compounds, four indeterminate and nine untested.
Its metrics describe only the classified subset and must not be compared as
though they used the full 18-compound cohort. Neither convention establishes
clinical safety.

**The corrected 87% sensitivity is not reproduced.** Complete compound-level
protein-binding-corrected margins were not recovered from the inspected sources.
Table 6 counts are included as reported-only reference data. The corrected chip
threshold of 375 was selected on the study data, and the headline two-donor
result covers 18 shared drugs, not all 27. This is retrospective reproduction,
not external holdout validation.

## Experimental response rows

Supplementary Data 8 supplies 210 day-3 rows across six compounds and three
endpoints: 204 numeric values and six explicit `NA`/`NaN` entries. The manifest
preserves each sheet, row and missing marker. Dose is a multiple of human Cmax,
as shown in Figure 4, not a molar concentration. Endpoint units are normalized
albumin percent of control, ALT ng/day/10^6 hepatocytes, and morphology score.
Day comes from the workbook column headers. Donor and chip IDs are unavailable.

The report computes descriptive means and sample SEM by compound, endpoint and
dose (105 groups). Missing values are excluded; empty groups have null means and
SEM, and singleton groups have null SEM. The source rows must not be assumed to
be independent biological replicates. No dose-response curve fitting or IC50
estimation is performed.

## Run and verify

From a checkout with Forma's Python dependencies installed:

```bash
python -m forma_core.biology.ewart_liverchip examples/biology/ewart-liverchip-v0.json \
  --output /tmp/ewart-report.json
python -m pytest tests/projects/test_ewart_liverchip.py -q
```

The checked-in `examples/biology/ewart-liverchip-v0-report.json` is regenerated
and compared in tests. Normal audit execution exits zero when the report is
successfully produced, even when scientific discrepancies exist. Add
`--require-all-uncorrected-matches` to require complete Table 5 agreement; this
version intentionally exits **2** because of the donor-2 mismatch.

## Rebuild the dataset

The importer needs `openpyxl` (tested with 3.1.5); normal benchmark execution
does not. Download the three source files from the `sources` URLs in the manifest,
then run:

```bash
python scripts/biology/build_ewart_dataset.py \
  /path/to/article.xml /path/to/correction.xml \
  /path/to/43856_2022_209_MOESM8_ESM.xlsx \
  /tmp/ewart-liverchip-v0.json
```

The importer checks SHA256 before extraction. A source update requires review
and deliberate versioning; it cannot silently alter this dataset.

| Source | Locator | SHA256 |
|---|---|---|
| Article XML | Europe PMC PMC9727064, Tables 1, 4–6; Figure 4 for units | `48addc159dc30ffb628c4adc4f71dd170f8f3b0b5f4b2f71b5d8fdc7f5719468` |
| Correction XML | Europe PMC PMC9837064 | `0236ff10c88e6b336faf4b039bc941cf84ef07f16cf05dd303a30f0ff2ae33f7` |
| Supplementary Data 8 | Sheets ALBUMIN, ALT, Morphology | `87cc22d0c1d4508f7e0830df348c52238bdb18d821c8d29cc0751114081509fc` |

Table 1 XML has a blank compound name at row 16. The importer explicitly restores
Olanzapine using Table 4 row 16 and the Clozapine matched pair in Tables 1–2.
The compound record carries an identity-repair note; all other identities must
match exactly between Tables 1 and 4.

## Attribution and reuse

The derived dataset is attributed to Ewart et al. and distributed under the
source article's [Creative Commons Attribution 4.0 license](https://creativecommons.org/licenses/by/4.0/).
The article includes supplementary material under that license unless a separate
credit states otherwise; no conflicting credit was found in the extracted data.
Changes are structured transcription, the documented identity repair, explicit
missing-value normalization, and added metadata and descriptive statistics.
The source XML and workbooks are not bundled. Code remains under the repository's
license. No DILImap data is included.
