# Biological experiment interface

Forma's biological layer is an application-facing metadata contract that composes
with the existing reusable `FluidicSystem`. It records the biological question,
compartments, exposures, controls, endpoints, sampling, observations, external
reference outcomes and provenance without turning the generic fluidics schema into
an organ-specific model.

This milestone does **not** implement a toxicity predictor, biological simulator,
clinical safety assessment or wet-lab protocol generator.

## Models

Import the contract from `forma_core.biology`:

```python
from forma_core.biology import BiologicalExperiment, validate_biological_experiment
from forma_core.workspaces.projects.models import HardwareIntermediateRepresentation

project = HardwareIntermediateRepresentation.model_validate_json(project_json)
experiment = BiologicalExperiment.model_validate_json(experiment_json)
issues = validate_biological_experiment(experiment, project.fluidic_system)
```

`BiologicalExperiment` contains:

- `BiologicalCompartment`: cell/tissue metadata plus the channel/chamber IDs that physically host it.
- `CompoundExposure`: declared compound, concentration metadata, timing and evidence references.
- `ExperimentalControl`: untreated, vehicle, positive, negative or reference comparison arms.
- `BiologicalEndpoint`: planned viability, injury, function, imaging, omics, biomarker or other measurements.
- `SamplingPoint`: planned time, compartment and endpoints.
- `DatasetReference`: source/version/license/citation metadata for external evidence.
- `BiologicalObservation`: imported or measured values with mandatory dataset provenance.
- `ReferenceOutcome`: external labels such as a DILI reference category, kept separate from observations and predictions.

Internal IDs and references are checked during Pydantic validation. The deterministic
`validate_biological_experiment` adapter checks that biological compartments map to
real fluidic channels/chambers when a `FluidicSystem` is supplied.

## Liver DILI example

`examples/organ-on-chip/liver-dili-biological.json` layers a liver/DILI study
scenario on the existing validated two-channel organ-chip fixture. It uses an FDA
DILIrank reference record to demonstrate provenance, while the concentration field
is deliberately reference-relative rather than a wet-lab dose recommendation.

Run the integrated check:

```sh
python -m forma_core.biology.benchmark \
  examples/organ-on-chip/liver-dili-biological.json \
  --project examples/organ-on-chip/two-channel.json
```

The command validates both the existing fluidic system and the biology-to-fluidics
links and emits JSON suitable for CI or a demo. Its `claims` block is deliberately
explicit that toxicity prediction, biological simulation and clinical safety
assessment are false for this milestone.

## LiverBench v0

`examples/biology/liverbench-v0.json` is a hand-audited 24-compound reference slice
joined across two FDA Liver Toxicity Knowledge Base resources:

- DILIrank 2.0: 1,336 FDA-approved drugs ranked as `vMost`, `vLess`, `vNo` or
  `Ambiguous-DILI-concern` on the FDA source page.
- DILIst: 1,279 drugs with a binary human DILI classification on the FDA source
  page (768 positive, 511 negative; 0 = negative, 1 = positive).

The v0 slice is balanced 12 positive / 12 negative and split 12 train / 6 dev /
6 heldout. It deliberately includes eight challenge records: four DILIst-positive
drugs that are only `vLess-DILI-concern` in DILIrank, and four DILIst-negative
records that are `Ambiguous-DILI-concern` in DILIrank. The purpose is to prevent
the initial benchmark from containing only easy high-concern versus no-concern
examples.

Every row retains the FDA source record IDs, source compound names, DILIrank
severity/concern, DILIst classification, route, cohort and split. The repository
stores only this small derived manifest rather than mirroring the complete FDA
lists.

Validate the dataset and exercise all 24 records through the biological→fluidic
interface:

```sh
python -m forma_core.biology.liverbench \
  examples/biology/liverbench-v0.json \
  --project examples/organ-on-chip/two-channel.json
```

That command should report interface coverage; it is **not** a toxicity-performance
result. LiverBench itself generates no predictions.

To score a real model, provide a prediction bundle:

```json
{
  "model_name": "example-model",
  "model_version": "commit-or-version",
  "predictions": [
    {"record_id": "ketoconazole", "predicted_label": 1, "score": 0.93},
    {"record_id": "valproic-acid", "predicted_label": 1, "score": 0.87}
  ]
}
```

Then run, normally against the held-out split:

```sh
python -m forma_core.biology.liverbench \
  examples/biology/liverbench-v0.json \
  --predictions results/predictions.json \
  --split heldout
```

Complete prediction sets report sensitivity, specificity, false-negative rate,
accuracy, balanced accuracy and AUROC when scores are supplied. Incomplete or
unknown record IDs fail closed instead of silently computing a partial result.
Unit tests use synthetic predictions only to verify scorer math; those test values
must never be presented as model performance.

FDA source pages:

- https://www.fda.gov/science-research/liver-toxicity-knowledge-base-ltkb/drug-induced-liver-injury-rank-dilirank-20-dataset
- https://www.fda.gov/science-research/liver-toxicity-knowledge-base-ltkb/drug-induced-liver-injury-severity-and-toxicity-dilist-dataset

## Boundary

Keep generic physical primitives in `forma_core.fluidics`. Organ, cell, compound,
assay and dataset semantics belong in the biological/application layer. Future
DILI prediction or digital-twin work should consume this contract and produce
provenanced observations/predictions rather than adding hidden biological behavior
to the fluidic validator.
