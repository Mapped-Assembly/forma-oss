# Liver-chip end-to-end demo

Run result: PASS

Scope: deterministic engineering fixture → validation → known-fault repair → analytical flow perturbation → published drug evidence.

Compound: **Troglitazone**

## Engineering checks

Initial design passes: True

| Injected fault | Detected | Repair passes |
|---|---|---|
| missing_outlet | True | True |
| reversed_connection | True | True |
| excessive_flow | True | True |

## Flow perturbation

| Channel | Velocity ratio | Pressure-drop ratio | Residence-time ratio |
|---|---:|---:|---:|
| vascular_channel | 2.00 | 2.00 | 0.50 |
| epithelial_channel | 2.00 | 2.00 | 0.50 |

## Published evidence

36 source rows: 32 measured values and 4 missing results. Status: partial.

See evidence.json for doses, units, source hashes, row references, descriptive means and SEM.

## Separate molecular baseline

The run also executes the existing PubChem 3-NN comparator on its six-compound heldout slice. See molecular-baseline.json. This is not a prediction for the selected evidence compound, and its performance must not be attributed to the chip.

## Limits

This run does not call an LLM, simulate injury, train a toxicity model, or test a physical chip. Repairs target known injected faults. The separate molecular baseline is not a chip predictor.

## Artifacts

design.json, requirements.json, experiment.json, evidence.json, molecular-baseline.json, run.json.
