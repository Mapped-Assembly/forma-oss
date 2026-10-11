# LiverBench baseline status

LiverBench v0 has 24 compounds: 12 train, 6 dev and 6 held out. Its biology and
fluidics checks validate experiment representation, not simulated liver toxicity.

## Available baselines

| Baseline | Inputs | Supervision | Held-out coverage | Meaning |
| --- | --- | --- | --- | --- |
| DILIrank severity | FDA severity metadata | Fixed rule | 6/6 | Related-source reference; DILIst and DILIrank are not independent |
| PubChem 3-NN | Five molecular descriptors | Train + dev DILIst labels only | 6/6 | Molecular-property baseline, independent of DILIrank input features |
| Optional IC10/Cmax | Locally supplied biological assay estimates and exposure data | Fixed rule; no label fitting | Depends on supplied data | Cytotoxicity-only baseline with explicit abstentions |

None establishes organ-on-chip performance or clinical safety. Independence of
input features does not establish independent external validation.

## Reproduce the molecular baseline offline

```bash
python -m forma_core.biology.liverbench_independent \
  examples/biology/liverbench-v0.json \
  examples/biology/liverbench-v0-pubchem-descriptors.json \
  --predictions-output /tmp/liverbench-pubchem-predictions.json
```

The fixed model uses population z-scores fitted on train+dev descriptors,
Euclidean distance, and three neighbors. Ties are broken by benchmark ID. The
positive score is the fraction of positive neighbors; classification uses 0.5.
The six held-out labels do not participate in scaling or voting.

The small held-out slice gives TP=3, TN=1, FP=2, FN=0: sensitivity 1.0,
specificity 0.3333, balanced accuracy 0.6667 and AUROC 0.5. Six compounds are
insufficient for a performance/generalization claim. These results are separate
from biological-assay results; the two must never be pooled to imply measured
biological coverage.

## Optional local biological-assay adapter

The adapter accepts two UTF-8 CSVs (the DILImap layout is supported):

- Viability: `Compound`, `IC10_uM`.
- Exposure: `LIBRARY CMPDS`, `Cmax_median` (also in micromolar).

Provide inputs you have rights to use, with a provenance URI:

```bash
python -m forma_core.biology.liverbench_assay \
  examples/biology/liverbench-v0.json \
  /path/to/licensed/viability.csv /path/to/licensed/cmax.csv \
  --source-uri 'https://your-data-source.example/dataset/version' \
  --output /tmp/liverbench-assay-audit.json
```

Every input file gets a SHA-256 digest. Compound matching ignores case and outer
whitespace only. Synonyms, salts and chemical forms are not guessed. Duplicate
normalized source names and invalid numeric values fail closed. Every benchmark
ID remains in the coverage manifest, including compounds absent from the source.

The fixed rule predicts positive for **IC10 / Cmax < 80**, a cytotoxicity-margin
component described in the pinned [DILImap source](https://github.com/Cellarity/DILImap/blob/00d7e4ea232d18109c27cbbec131f09f4ed6245f/dilimap/models.py).
This adapter implements arithmetic independently and does not import upstream
code or weights. It is **not a reproduction of ToxPredictor**, which also uses
transcriptomics and additional exposure logic. The monotone ranking score
`1 / (1 + margin)` is not a calibrated probability. The threshold is fixed from
the reference, not selected against LiverBench labels.

A missing IC10 remains unknown. It is not replaced with infinity, a maximum
dose, or a negative prediction. Missing source rows and missing estimates have
separate abstention reasons. The existing strict scorer suppresses all full-split
metrics if any selected compound lacks a prediction. No partial-subset metric is
presented as full-split performance.

The normal CLI exit code of zero means the **coverage audit ran successfully**.
Use `--require-complete` to require full split coverage; that gate returns 2 when
any compound is missing. Invalid inputs fail with an error. An empty prediction
set is explicitly reported as `null`, with all selected compounds abstained.

## Why DILImap is not bundled

The [upstream license](https://github.com/Cellarity/DILImap/blob/00d7e4ea232d18109c27cbbec131f09f4ed6245f/LICENSE)
restricts data use to academic/non-commercial research, excludes internal use at
for-profit companies, and prohibits repackaging raw data without permission.
The code also carries non-commercial restrictions. This repository therefore
includes no DILImap data, copied implementation, model weights or automatic
downloader. Availability at a public URL does not establish permission for
commercial use. The local adapter's unit tests use only synthetic measurements.

The initial source-coverage audit found assay rows for 11/24 LiverBench compounds,
including 3/6 held-out compounds. Only 2/6 held-out compounds had both a reported
IC10 and Cmax; the third had no reported IC10 estimate. That is a coverage result,
not an evaluated biological baseline or a negative toxicity finding.

## Next biological milestone

Obtain an appropriately licensed assay dataset covering both DILI classes in the
unchanged held-out split, or define a separately versioned benchmark with its own
predeclared split. Audit compound identity and upstream model-training overlap
before reporting independent validation. Preserve absent measurements and
experimental provenance. Do not silently fill biological gaps with molecular
predictions or relabel external hepatocyte data as Forma-generated chip data.

Reference: Bergen et al., *A large-scale human toxicogenomics resource for
drug-induced liver injury prediction*, Nature Communications 16, 9860 (2025),
https://doi.org/10.1038/s41467-025-65690-3.

The separate [Ewart Liver-Chip reproduction](ewart-liverchip.md) now provides
versioned published chip margins and experimental response rows. It reproduces
part of the publication and documents unresolved discrepancies; it does not
satisfy the independent-predictor validation milestone above.
