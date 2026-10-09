# FluidicSystem hackathon MVP

Issue [#3](https://github.com/Mapped-Assembly/forma-oss/issues/3) adds one optional
`fluidic_system` field to `HardwareIntermediateRepresentation`. The IR name,
version, mechanical/electrical fields and serialization remain unchanged.
Payloads that omit the field still work. This milestone-scoped contract informs
the future architecture work in #2; it does not implement that refactor.

![Two-channel organ-chip flow schematic](assets/organ-on-chip-flow.gif)

The GIF is an exploded schematic rendered from the checked example JSON. It is
not a CAD export or CFD result. Channel tracers move at the declared flow divided
by channel cross-sectional area; layer gaps, chambers, cells and external tubing
are illustrative. No membrane transport or biological response is simulated.

## Use the contract

Models, graph traversal, validation, calculations, examples and scoring live in
`forma_core/fluidics/`. Import the typed models from `forma_core.fluidics.models`.

```python
from forma_core.fluidics.examples import organ_on_chip_system
from forma_core.validation import validate_project
from forma_core.workspaces.projects.models import HardwareIntermediateRepresentation

project = HardwareIntermediateRepresentation(fluidic_system=organ_on_chip_system())
issues = validate_project(project)  # electrical checks plus optional fluidics
assert not issues
assert HardwareIntermediateRepresentation.model_validate_json(project.model_dump_json()) == project
```

The OpenCode authoring tools expose this schema in their existing project JSON
argument. Their compile, update and validation operations check fluidics. The
web-research architect can return `WebProjectPlan.fluidic_system`; both staged
and legacy packaging retain it and include blocking fluidics diagnostics. CLI
validation, project iteration, saved outcome evaluation, A2A compilation and
canonical-revision consistency checks also include the fluid network. No new
provider call, migration, runtime dependency or environment variable is needed.

## Authoring rules

| Entity | Meaning and requirements |
| --- | --- |
| Inlet / outlet | Boundary source / terminal sink; every declared boundary must participate in a complete directed flow path. Outlets declare `waste`, `product` or `exhaust`. |
| Reservoir | Positive `volume_ul`, contents, and role `supply`, `junction` or `waste`. Junctions use the same steady-state conservation checks as other internal nodes. |
| Pump / valve | Inline graph nodes. Optional channel `pump_id` / `valve_id` must exist and be an endpoint of that channel. Valves represent the nominal open configuration. |
| Channel | `source_id` and `target_id` reference nodes, never other channels. Length, width and height are finite positive mm values. Material and fluid name are required. |
| Chamber | Positive volume, contents, optional temperature; `inlet_ids` and `outlet_ids` list **all incident channel IDs**, exactly once. |
| Membrane | References two channels or chambers in separate circuits; declares material and positive thickness, optionally pore size and porosity. It never creates a bulk-flow graph edge. |
| Fluid properties | Optional explicit viscosity in Pa·s, density in kg/m³, temperature, liquid/gas phase and Newtonian flag. `channel.fluid` matches the property record's `id`. Unknown properties are never substituted. |

All entity IDs, including property records and membranes, are globally unique.
Extra fields and nonfinite numeric values are rejected. Each node's `circuit_id`
identifies a bulk-fluid isolation group (`default` for a single circuit).
Channels crossing groups are invalid. Give separated organ-chip channels
distinct circuits; a dosing inlet joins the intended circuit, upstream of its
mixing chamber, without entering the other circuit.

`FluidicSystem.model_validate` rejects invalid schemas, dimensions and duplicate
IDs. `validate_fluidic_system` returns structured blocking findings for graph and
operating-constraint errors, allowing an invalid draft to remain inspectable.
It also rechecks schema invariants after in-process edits. The normal project
validation adapter maps these findings to `CRITICAL` issues. Parsing alone does
not certify a network or update the IR's stored `is_valid` flag: run validation.

Checks cover unresolved endpoints, source-to-source / sink-to-sink / self edges,
disconnected components (including cycles), missing outlet paths, complete
chamber ports, pump/valve references, membrane references and circuit isolation.
Directed recirculation is allowed only when every node remains reachable from a
source and can reach an outlet. Membranes do not establish these flow paths.

Targets and bounds use µL/min. If supplied, bounds need a target to verify them.
All known incoming and outgoing flows at an internal node must balance, and
pump targets/capacity are checked against adjacent flow sums. Unknown branch
flows are not solved. A zero target is representable in the structural network;
it does not imply active perfusion or a finite residence time. Valve control,
pump head curves, reservoir accumulation and transient operation are out of scope.

## Physical estimates

The helpers operate on a rectangular channel with an explicitly supplied target
flow. With width `w`, height `h`, length `L` and volumetric flow `Q`:

| Helper | Calculation |
| --- | --- |
| `cross_sectional_area_mm2` | `w * h` |
| `channel_volume_ul` | `w * h * L` (1 mm³ = 1 µL) |
| `average_velocity_mm_s` | `(Q / 60) / (w * h)` for Q in µL/min |
| `residence_time_s` | `volume * 60 / Q`; zero or missing Q raises |
| `reynolds_number` | `rho * velocity * hydraulic_diameter / mu`, in SI units |
| `pressure_drop_kpa` | Approximate `12 mu L Q / [w h³ (1 - 0.63 h/w)]`, with the smaller transverse dimension used as h |
| `mean_wall_shear_stress_pa` | Wetted-perimeter mean `Δp * area / (length * perimeter)`; **not** local cell-surface shear |

Pressure/shear estimates require explicit viscosity and density, a matching
liquid property record, Newtonian flow and Reynolds number below 2000. This
threshold is a scope guard, not proof that entrance or inertial effects are
negligible. Assumptions are steady, fully developed, incompressible laminar flow
in rigid, straight, constant-section channels. No branch pressure solve, minor
losses, PDMS deformation, membrane leakage or biological validation is provided.
The rectangular pressure approximation is less accurate near square sections.

`max_pressure_kpa` is a **channel differential-pressure budget**, not an absolute
pressure rating or a pump-head limit. If it is supplied, insufficient inputs or
an unsupported regime are blocking `pressure_unknown` findings. Without a
pressure budget, geometric/topological checks can run without fluid properties;
calling a pressure helper still fails clearly if those properties are absent.

Sources for the approximations and limitations:

- [In situ pressure measurement within deformable rectangular PDMS microfluidic devices](https://pmc.ncbi.nlm.nih.gov/articles/PMC3365910/), rectangular resistance approximation and deformation limitations.
- [Towards an Optimal Pressure Tap Design for Fluid-Flow Characterisation at Microscales](https://pmc.ncbi.nlm.nih.gov/articles/PMC6479773/), rectangular-channel force balance relating pressure drop to mean wall shear.

## Examples and benchmark

`examples/organ-on-chip/` contains full Hardware IR JSON, separate task
specifications, and an intentionally broken network:

- `two-channel.json`: vascular 30 µL/min and epithelial 10 µL/min, separate waste,
  a membrane, pumps, distribution chambers and explicit illustrative properties.
- `with-dosing.json`: additional 5 µL/min inlet and inline valve feeding the
  vascular chamber; the vascular outlet channel carries the summed 35 µL/min.
- `broken-missing-outlet.json`: vascular channel points at an undeclared waste
  endpoint and must fail.

Run from the repository root after installing Forma's Python dependencies:

```sh
python -m forma_core validate examples/organ-on-chip/two-channel.json
python -m forma_core.fluidics.benchmark examples/organ-on-chip/two-channel.json --spec examples/organ-on-chip/two-channel-spec.json
python -m forma_core.fluidics.benchmark examples/organ-on-chip/with-dosing.json --spec examples/organ-on-chip/with-dosing-spec.json
python -m forma_core.fluidics.benchmark examples/organ-on-chip/broken-missing-outlet.json --spec examples/organ-on-chip/two-channel-spec.json
python -m pytest tests/projects/test_fluidics.py -q
python scripts/media/render_fluidic_demo.py --output docs/assets/organ-on-chip-flow.gif
```

The broken example exits 1. Scoring accepts a raw network or full IR and returns
eight named checks, findings, `passed`, and an equally weighted score in [0,1].
The external spec fixes required source-to-waste paths, channel flow targets and
membrane-separated pairs. A topologically valid but wrong design therefore
cannot pass. Malformed schemas score zero; structurally incomplete designs can
earn a partial score but never pass. Only all eight checks passing returns exit 0.
The checked fixtures score 1.0; this is deterministic fixture validation, not a
measured model-generation success rate.

The included renderer is deliberately specific to the two-channel fixture and
rejects added branches rather than hiding them. It requires Pillow (already an
optional Forma terminal/backend dependency). It does not change OpenCAD/exporters
or add a fluidics UI. Use the JSON and benchmark report as the machine-readable
deliverables for the hackathon.
