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

## Boundary

Keep generic physical primitives in `forma_core.fluidics`. Organ, cell, compound,
assay and dataset semantics belong in the biological/application layer. Future
DILI prediction or digital-twin work should consume this contract and produce
provenanced observations/predictions rather than adding hidden biological behavior
to the fluidic validator.
