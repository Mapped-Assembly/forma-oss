# LiverChip prediction and evaluation plan v0.1

Status: task and admission rules defined; **no independent test cohort admitted**.
This is a versioned analysis plan, not a completed validation or a registered
prospective study. Decisions below precede any new model fitting in this work.

## Intended prediction

Given experimentally measured liver-assay responses for a compound absent from
model development, predict whether that compound belongs to the source's human
DILI-positive or DILI-negative reference class. The evaluation unit is the
**compound**, never an individual well, dose, day or donor measurement.

The primary intended application is a liver-chip assay interpreter. It requires
measured assay data for the new compound. It does not infer a novel drug's liver
response from its name, produce a patient-specific risk probability, or establish
a safe dose. Predicting from chemical structure alone is a separate comparator.

The first output contract is:

- `compound_id`: audited chemical identity, with parent and tested form recorded.
- `score`: uncalibrated DILI ranking score with declared direction, or null.
- `predicted_label`: 0, 1, or null when abstaining.
- `abstention_reason`: missing assay, incompatible assay, unresolved identity,
  unresolved censoring, out-of-domain, or another predeclared reason.
- `model_version`, `feature_contract_version`, source hashes and observation IDs.

A negative prediction means classification against a benchmark reference label;
it must never be rendered as “safe.” Clinical reference labels are imperfect and
must retain their original definitions and provenance.

## Inputs and leakage boundary

Permitted inputs are measured endpoint values, their controls/normalization,
dose, time, source platform, donor metadata when supplied, and measured or sourced
human Cmax with explicit total/free conventions and units. Preserve censoring and
missingness. Biological replicates, technical replicates and donors must remain
distinguishable where source metadata permits it.

Human DILI labels, severity ranks, label-section text, published final DILI
classifications, drug names and identifiers used as predictive features, and
label-bearing literature summaries are prohibited predictor inputs. IDs may be
used for joins only. Do not feed the full evidence report to an LLM predictor:
it includes reference labels and published margins intended for inspection.

Define a numeric feature contract separately for each assay platform. Do not
pool day-3 albumin/ALT/morphology, day-14 ATP viability, IC10, and IC50 as equivalent
measurements. Do not infer a missing Cmax or convert a censored limit into an exact
value. The existing six-drug Ewart response subset is insufficient to develop and
evaluate a general-purpose multivariate classifier.

## Dataset decision

| Source | Decision | Reason and boundary |
|---|---|---|
| Existing Ewart 2022 data | Development and reproduction only | Already inspected extensively; 27 summary compounds and six with response rows. No fresh holdout claim. |
| Existing LiverBench v0 | Software regression and molecular comparator only | All 24 compounds have been used or inspected. Retain its original split for historical reproducibility; exclude all 24 from a new external test. |
| Proctor 2017, 110 drugs | **Selected candidate external assay-transfer panel** | Separate 3D human liver microtissue experiments with IC50/exposure information; must pass identity, feature and upstream-use audits. This is not a perfused-chip validation cohort. |
| Vorrink 2018, 123 drugs | Secondary candidate; not selected as a fresh Ewart comparator | Different spheroid conditions and endpoint/time contract. Audit links to the spheroid comparator already inspected in Ewart before any admission. |
| FDA DILIrank 2.0 / DILIst | Reference-label provenance and molecular baseline resources | DILIst augments DILIrank and literature; they are not independent label sources. They supply labels, not chip-response measurements. |
| DILImap | Not selected for redistribution or commercial project use | Existing source audit found noncommercial restrictions and insufficient heldout assay coverage. Obtain suitable rights before use. |
| New, compatible liver-chip cohort from a separate laboratory/study | **Required primary external validation source** | No suitable independent cohort has yet been acquired or admitted. Must match the intended endpoint/feature contract and include both classes. |

Proctor et al. compare 14-day 3D microtissues with 2-day plated hepatocytes across
110 drugs. The source assigns 69 positives and 41 negatives. Its article is
CC BY 4.0. The initial audit transcribes Table 1 identities, not assay measurements.
The source text contains unusual spellings, including `Benaxoprofen` and
`Sitax(s)entan`; these may hide overlaps with our existing data and are not
silently repaired.

The reproducible candidate manifest reports **26 exact normalized-name exclusions,
84 unresolved candidates, and zero admitted test compounds**. “Unresolved” does
not mean independent. Additional exclusions will be required after chemical
identity and upstream-use review. Counts are feasibility findings, not a promised
final test size or a model-performance result.

The source article and aggregate results have been read. Any eventual evaluation
on its data must be called a **retrospective external assay-transfer evaluation**,
with that exposure disclosed. It cannot establish prospective prediction or the
performance of a physical Forma chip.

## Independence and admission requirements

A test record is admitted only after all of the following are documented:

1. **Chemical identity:** record tested form, parent compound, canonical structure
   and InChIKey, reference identifiers and manual decisions. Group salts, synonyms,
   stereochemical variants and duplicates conservatively; quarantine unresolved
   identities. Structure-level disjointness is required, not merely different names.
2. **Development exclusion:** remove every compound used in training, feature
   selection, calibration, threshold selection or prior evaluation that informed
   model choices. Include all 24 LiverBench and 27 Ewart compounds, and every
   upstream model/pretraining dataset. Unknown upstream coverage blocks an
   independence claim for that model.
3. **Experimental independence:** record originating study, laboratory, donor,
   platform and any reuse of measurements. A new download or publication is not
   a new experiment. Shared measurements cannot cross development and test.
4. **Label provenance:** preserve original labels and trace literature overlap.
   Shared clinical annotation sources must be disclosed; do not claim independent
   label ascertainment without evidence. Contradictions remain flagged, not resolved
   by whichever choice improves performance.
5. **Feature compatibility:** verify raw/numerical assay availability, units,
   controls, exposure timing, censoring and Cmax conventions. Incompatible rows
   remain in the accounting with a reason, rather than disappearing after scoring.
6. **Reuse and freeze:** document applicable rights, pin source and derived file
   hashes, freeze the cohort and feature contract, and record code/model hashes
   before prediction. Keep labels out of inference inputs. An independent custodian
   is preferred for a genuinely blinded future cohort.

For clinical-label binarization, preserve the source rule: Ewart/Proctor ranks
1–3 positive, 4–5 negative. Report rank-4 enzyme-elevation records separately and
repeat the evaluation excluding rank 4 as a predeclared sensitivity analysis.
Do not replace this outcome with FDA Most-vs-No concern without creating a new
explicit task version. Conflicting sources must not be silently merged.

## Split and model-selection rules

All existing inspected data are development/exploratory for this new task.
Within a larger compatible development set, group all rows of a compound and
close chemical families together. Use grouped nested cross-validation for model
selection; fit scaling, imputation and feature selection inside training folds.
Report donor/study transfer separately. Random measurement-row splitting is banned.

Before opening a frozen external test, register the selected model, features,
threshold, allowed abstentions and exact cohort hash. Any tuning after observing
external results consumes that cohort as development evidence and requires a new
external cohort for the next confirmatory claim. Public or pretrained models with
unknown label exposure can be exploratory comparators only.

The first model should be a transparent baseline using the smallest compatible
assay feature set, compared against a constant classifier and the existing
structure-only baseline where inputs are available. Do not choose a model family
or pretend to train it until the compatible development sample size and class
coverage are known. Published thresholds chosen on a proposed test source are
not independent baselines on that source.

## Metrics and acceptance

Primary operating-point metric: compound-level sensitivity, with the threshold
chosen exclusively on development predictions to target at least **80% specificity**.
That target is a project design choice, not a clinical or regulatory standard.
Freeze tie-breaking before evaluation. If no development threshold meets the target
with usable sensitivity, report failure rather than lowering the target on test.

Report test specificity, TP/TN/FP/FN, balanced accuracy, AUROC, AUPRC, class counts,
and prediction coverage. A score is not a calibrated probability. If probability
calibration is later added, fit it only in development and report calibration
separately. Use compound-level 95% uncertainty intervals; do not treat the 210
response rows as 210 independent compounds. For paired baseline comparisons,
resample compounds together, not individual observations.

Publish the denominator and reasons for every abstention, including coverage by
class/platform. Full-cohort binary metrics require complete predictions. For
partial coverage, suppress full-cohort headline metrics and label classified-only
metrics explicitly; show conservative sensitivity/specificity bounds obtained by
counting abstentions as wrong versus correct. Never optimize exclusion criteria
against test labels.

There is no predeclared “validated” claim from a small convenience panel. Before
confirmatory data collection, calculate required positive and negative compound
counts from desired interval precision and a scientifically reviewed effect target.
Until that design is funded and frozen, any small-panel result is exploratory.

## Concrete next work

1. Audit Proctor Supplementary Data 3 identities and numerical assay coverage,
   retaining censoring and source units. Confirm supplement-specific credits.
2. Resolve parent-structure matches against the 49 unique names in the union of
   our current manifests; audit any additional model development/pretraining sets.
3. Produce an admission report listing eligible and excluded records and platform
   compatibility. Keep `independent_test_ready=false` until every gate passes.
4. Obtain a compatible separate liver-chip cohort for the primary task. Draft a
   data request with endpoint, dose, time, donor, control and clinical-label fields;
   send only after explicit authorization. No outreach was sent in this work.
5. Freeze the model/feature contract and then evaluate once. Do not start a model
   training run merely to fill the current data gap.

## Reproduce the feasibility audit

Download the pinned Proctor XML from the source URL in the candidate manifest:

```sh
python scripts/biology/audit_evaluation_candidates.py \
  /path/to/proctor.xml \
  examples/biology/ewart-liverchip-v0.json \
  examples/biology/liverbench-v0.json \
  /tmp/liverchip-evaluation-candidates-v0.json
```

The script requires only the Python standard library and rejects changed source
bytes. It is an audit, not a splitter or an independence certification.
The machine-readable decisions are in
`examples/biology/liverchip-prediction-plan-v0.json`.

## Sources and attribution

- Proctor et al. (2017), [article](https://doi.org/10.1007/s00204-017-2002-1),
  [source XML](https://www.ebi.ac.uk/europepmc/webservices/rest/PMC5515971/fullTextXML).
  SHA256 `88c13554a2898d5b3857143f949ec3316b2da2f1b182207e2ccf92def3e97e90`.
  Derived Table 1 facts attributed under [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/);
  original spellings retained, overlap flags added.
- Vorrink et al. (2018), [article](https://doi.org/10.1093/toxsci/kfy058),
  [source XML](https://www.ebi.ac.uk/europepmc/webservices/rest/PMC5974779/fullTextXML).
  SHA256 `ab3accfe5409b7772a21d00836a677dfff05998ec41d01191ea4601ba3f44c70`.
- FDA [DILIrank 2.0](https://www.fda.gov/science-research/liver-toxicity-knowledge-base-ltkb/drug-induced-liver-injury-rank-dilirank-20-dataset)
  and [DILIst](https://www.fda.gov/science-research/liver-toxicity-knowledge-base-ltkb/drug-induced-liver-injury-severity-and-toxicity-dilist-dataset).
- Existing [Ewart source audit](ewart-liverchip.md) and
  [DILImap limitations](liverbench-baselines.md#why-dilimap-is-not-bundled).

Sources checked 2026-10-11. Candidate selection, exclusions, metrics and gates are
our proposed evaluation design, not findings claimed by the source authors.
