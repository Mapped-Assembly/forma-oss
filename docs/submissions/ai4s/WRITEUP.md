**Submission category: End-to-End System**

# Forma Liver-Chip: Auditable Engineering and Experimental Evidence

Team: Mapped-Assembly. Project lead: Isayah Culbertson. Other team members and
registration status require confirmation before submission.

Demo video: **not yet recorded/published**.

Public code: https://github.com/Mapped-Assembly/forma-oss

## Project summary

Liver-on-chip research combines physical device constraints, experimental metadata
and biological measurements. These layers are often handled separately, making
it difficult to trace whether an experiment is structurally valid, which results
are observed rather than inferred, and where evidence is missing.

Forma Liver-Chip connects these layers in a reproducible software workflow. A
single command builds a declared two-channel fixture, validates it against external
requirements, injects and detects three representative engineering defects,
applies explicit corrections, and verifies the revised designs. Analytical
channel calculations demonstrate how velocity, pressure drop and nominal residence
time change when flow doubles. The workflow then attaches published drug-response
observations to a typed biological experiment with units, source hashes, row
references and explicit missing-value markers. It also runs a separate molecular
nearest-neighbor baseline so that simple predictive modeling can be inspected
without attributing its results to the physical chip.

The checked Troglitazone example contains 36 source rows: 32 measured values and
four missing entries. All three injected engineering faults are detected and the
three prescribed corrections pass validation. These results demonstrate software
integration on declared examples, not clinical prediction or physical validation.

The minimum demo is entirely offline and uses a deterministic fixture builder.
It does not claim live language-model design generation or a validated biological
digital twin. Its value is a checkable interface between design representations,
engineering calculations and traceable experimental evidence, providing a concrete
foundation for evaluating future AI design agents and biological predictors.

## Technical report

### Problem and scope

The target user is an assay developer evaluating liver-chip experiment
configurations. The immediate question is whether a declared design satisfies
explicit physical/interface requirements and can carry experimental evidence
without losing provenance. Predicting clinical liver injury from a novel drug is
a separate, unfinished research objective.

### Architecture and implementation

Python/Pydantic models represent generic channels, chambers, pumps, outlets and
membranes in HardwareIntermediateRepresentation. A separate BiologicalExperiment
represents compartments, endpoints, observations and reference outcomes. The
`liverchip_demo` entry point orchestrates existing builders, validators,
calculations and evidence adapters. No LLM API is called by this offline run.

The two perfusion circuits have separate outlet paths and a declared porous
interface. Fixture dimensions and fluid properties are illustrative inputs.
External requirements remain separate from the candidate design. Validation
checks structure, topology, required paths, geometry and declared operating limits.

The defect demonstration removes the vascular outlet, reverses a vascular
connection and raises a channel flow above its declared limit. Each correction
restores the affected field from the declared fixture requirement. This is a
known-fault repair demonstration, not evidence of general autonomous repair.

### Analytical model

For a rectangular channel, mean velocity is Q/A and nominal residence time is
V/Q. Hydraulic diameter is 2wh/(w+h), with Reynolds number calculated from supplied
viscosity and density. Pressure drop uses the rectangular laminar approximation
12 μ L Q / [w h³ (1 − 0.63 h/w)], with h ≤ w. Mean wall shear follows the pressure
force balance over the wetted perimeter. These estimates assume rigid, straight,
fully developed Newtonian liquid flow. They do not model metabolism, adsorption,
membrane transport or injury. Doubling flow is a channel-level analytical check,
not validation of a new operating protocol.

### Data and provenance

The Ewart 2022 source is attributed under CC BY 4.0. Its derived manifest contains
27 compound summaries and 210 response rows across six drugs: 204 numerical
values and six explicit missing entries. Units, source sheets/rows, source hashes
and documented identity repairs are retained. The example associates these
external observations with a software compartment; it does not imply the fixture
produced them. Source day 3 is encoded as nominal 72 hours.

The separate LiverBench v0 molecular comparator uses five pinned PubChem
descriptors and a fixed 3-neighbor classifier. Scaling and neighbors use its
train+dev records, with six original heldout compounds scored separately. This
small, previously inspected slice is an exploratory reference and not an
independent chip-validation dataset. DILImap data are not bundled.

### Executed results

| Check | Result | Interpretation |
|---|---|---|
| Initial fixture | Pass | Declared engineering/interface requirements satisfied |
| Injected faults detected | 3/3 | Three specified defects, not general recall |
| Prescribed corrections validated | 3/3 | Known-fault repair demonstration |
| Flow doubled | Velocity ×2, pressure drop ×2, residence time ×0.5 | Both main channels satisfy the analytical relationships |
| Troglitazone source rows | 32 numerical + 4 missing | Published observations, not model predictions |
| Molecular reference | TP3, TN1, FP2, FN0; AUROC 0.5 | Six-compound exploratory structure baseline, not chip performance |

The checked JSON artifacts retain per-component findings and numerical outputs.
The separate Ewart reproduction recovers the uncorrected two-donor 80% sensitivity
and 100% specificity result, flags a donor-2 table discrepancy, and does not
reproduce the corrected 87% result. None of those published percentages is a Forma
predictor result.

### Reliability and limitations

Missing assay data remain missing; unavailable compounds are not assigned safe
outcomes. Reference labels are distinct from observations and predictions.
The minimum demo does not implement a free-form prompt parser, run a live LLM
baseline, validate biological responses, or fabricate a chip. The three injected
faults do not satisfy the broader RFD's proposed 20–30-scenario benchmark. No
independent, compatible external chip test cohort has been admitted.

### Reproduction

Follow README.md in this directory. The one-command run exports `REPORT.md`,
`design.json`, `requirements.json`, `experiment.json`, `evidence.json`,
`molecular-baseline.json` and `run.json`. A nonzero exit indicates failed workflow
checks or invalid inputs. No credentials are required.

### Licenses and references

Repository code is governed by its root LICENSE. Runtime dependency requirements
are in pyproject.toml; this demo primarily uses Python standard library and
Pydantic through Forma. It downloads no model weights and calls no external model
provider. AI coding assistance was used during implementation and documentation;
that is distinct from the algorithms executed by the demo.

- Ewart et al. (2022): https://doi.org/10.1038/s43856-022-00209-1 — CC BY 4.0; source hashes and modifications in the dataset manifest.
- FDA DILIst: https://www.fda.gov/science-research/liver-toxicity-knowledge-base-ltkb/drug-induced-liver-injury-severity-and-toxicity-dilist-dataset
- PubChem descriptor provenance: `examples/biology/liverbench-v0-pubchem-descriptors.json`.
- Physical model assumptions and references: `docs/fluidics.md`.
- Biological evidence and reproduction limitations: `docs/ewart-liverchip.md` and `docs/liverbench-baselines.md`.
