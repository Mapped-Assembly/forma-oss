"""Offline, deterministic scoring against an external organ-chip specification."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, ValidationError

from .models import FluidicModel, FluidicSystem, Identifier, NonNegative
from .topology import build_topology, reachable
from .validation import FluidicIssue, validate_fluidic_system


class RequiredPath(FluidicModel):
    source_id: Identifier
    waste_id: Identifier


class RequiredMembrane(FluidicModel):
    side_a_id: Identifier
    side_b_id: Identifier


class FluidicBenchmarkSpec(FluidicModel):
    """Requirements come from the task, never inferred from the candidate itself."""

    required_paths: list[RequiredPath] = Field(min_length=1)
    expected_flow_rates_ul_min: dict[Identifier, NonNegative] = Field(min_length=1)
    required_membranes: list[RequiredMembrane] = Field(min_length=1)


class FluidicBenchmarkResult(BaseModel):
    score: float
    passed: bool
    checks: dict[str, bool]
    issues: list[FluidicIssue] = Field(default_factory=list)
    schema_errors: list[str] = Field(default_factory=list)


def score_fluidic_system(payload: Any, spec: FluidicBenchmarkSpec) -> FluidicBenchmarkResult:
    """Score raw fluidic JSON or a full IR; malformed schemas score zero."""
    checks = dict.fromkeys([
        "schema", "topology", "flow_constraints", "pressure_constraints",
        "requested_paths", "requested_flows", "membranes", "isolation",
    ], False)
    if isinstance(payload, dict) and "fluidic_system" in payload:
        payload = payload["fluidic_system"]
    try:
        # Reparse models too, so mutated instances cannot bypass schema checks.
        system = FluidicSystem.model_validate(payload.model_dump() if isinstance(payload, FluidicSystem) else payload)
    except ValidationError as exc:
        return FluidicBenchmarkResult(score=0, passed=False, checks=checks, schema_errors=[
            f"{'.'.join(map(str, error['loc']))}: {error['msg']}" for error in exc.errors()
        ])
    issues = validate_fluidic_system(system)
    codes = {issue.code for issue in issues}
    checks["schema"] = True
    flow_codes = {code for code in codes if code.startswith(("flow_", "pump_flow_"))}
    pressure_codes = {code for code in codes if code.startswith("pressure_")}
    membrane_codes = {code for code in codes if code.startswith("membrane_")}
    checks["topology"] = not (codes - flow_codes - pressure_codes - membrane_codes - {"circuit_mixing"})
    checks["flow_constraints"] = not flow_codes
    checks["pressure_constraints"] = not pressure_codes
    graph = build_topology(system)
    wastes = {o.id for o in system.outlets if o.kind == "waste"} | {r.id for r in system.reservoirs if r.role == "waste"}
    checks["requested_paths"] = all(
        path.source_id in graph.sources and path.waste_id in wastes
        and path.waste_id in reachable(graph.forward, {path.source_id})
        for path in spec.required_paths
    )
    channels = {c.id: c for c in system.channels}
    checks["requested_flows"] = all(
        channel_id in channels and channels[channel_id].target_flow_rate_ul_min is not None
        and math.isclose(channels[channel_id].target_flow_rate_ul_min, flow, rel_tol=1e-6, abs_tol=1e-9)
        for channel_id, flow in spec.expected_flow_rates_ul_min.items()
    )
    membrane_pairs = {frozenset((m.side_a_id, m.side_b_id)) for m in system.membranes}
    checks["membranes"] = not membrane_codes and all(
        frozenset((m.side_a_id, m.side_b_id)) in membrane_pairs for m in spec.required_membranes
    )
    circuits = {c.id: graph.nodes[c.source_id].circuit_id for c in system.channels if c.source_id in graph.nodes}
    circuits.update({c.id: c.circuit_id for c in system.chambers})
    checks["isolation"] = "circuit_mixing" not in codes and all(
        m.side_a_id in circuits and m.side_b_id in circuits and circuits[m.side_a_id] != circuits[m.side_b_id]
        for m in spec.required_membranes
    )
    return FluidicBenchmarkResult(
        score=sum(checks.values()) / len(checks), passed=all(checks.values()), checks=checks, issues=issues,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("project", type=Path)
    parser.add_argument("--spec", required=True, type=Path)
    args = parser.parse_args()
    spec = FluidicBenchmarkSpec.model_validate_json(args.spec.read_text(encoding="utf-8"))
    result = score_fluidic_system(json.loads(args.project.read_text(encoding="utf-8")), spec)
    print(result.model_dump_json(indent=2))
    return 0 if result.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
