"""Offline, deterministic scoring against external fluid-system requirements."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError, model_validator

from .models import FluidicModel, FluidicSystem, Identifier, NonNegative, Positive
from .topology import build_topology, reachable
from .validation import FluidicIssue, validate_fluidic_system


class RequiredPath(FluidicModel):
    """Requested directed node-to-node path, optionally ending at an outlet kind."""

    source_id: Identifier
    target_id: Identifier
    outlet_kind: Literal["waste", "product", "exhaust"] | None = None

    @model_validator(mode="before")
    @classmethod
    def accept_legacy_waste_path(cls, value: Any) -> Any:
        """Read the original waste_id contract without weakening its semantics."""
        if not isinstance(value, dict) or "waste_id" not in value:
            return value
        payload = dict(value)
        waste_id = payload.pop("waste_id")
        if "target_id" in payload and payload["target_id"] != waste_id:
            raise ValueError("target_id and legacy waste_id must identify the same node.")
        if payload.get("outlet_kind") not in (None, "waste"):
            raise ValueError("Legacy waste_id requires outlet_kind='waste'.")
        payload.update(target_id=waste_id, outlet_kind="waste")
        return payload

    @property
    def waste_id(self) -> str | None:
        """Compatibility accessor for callers using the original waste-only API."""
        return self.target_id if self.outlet_kind == "waste" else None


class RequiredMembrane(FluidicModel):
    """Task-required porous interface between two channel or chamber IDs."""

    side_a_id: Identifier
    side_b_id: Identifier


class DimensionRange(FluidicModel):
    """Inclusive positive bounds in mm; at least one bound must be supplied."""

    minimum: Positive | None = None
    maximum: Positive | None = None

    @model_validator(mode="after")
    def validate_bounds(self) -> DimensionRange:
        """Reject empty or inverted ranges instead of silently passing them."""
        if self.minimum is None and self.maximum is None:
            raise ValueError("A dimension range requires a minimum or maximum in mm.")
        if self.minimum is not None and self.maximum is not None and self.minimum > self.maximum:
            raise ValueError("Dimension minimum must not exceed maximum.")
        return self

    def contains(self, value: float) -> bool:
        """Check a finite dimension against every supplied inclusive bound."""
        return math.isfinite(value) and (self.minimum is None or value >= self.minimum) and (
            self.maximum is None or value <= self.maximum
        )


class ChannelDimensionConstraints(FluidicModel):
    """Requested bounds for at least one rectangular channel dimension."""

    length_mm: DimensionRange | None = None
    width_mm: DimensionRange | None = None
    height_mm: DimensionRange | None = None

    @model_validator(mode="after")
    def require_dimension(self) -> ChannelDimensionConstraints:
        """Reject constraints that do not select a dimension to evaluate."""
        if self.length_mm is None and self.width_mm is None and self.height_mm is None:
            raise ValueError("Supply at least one of length_mm, width_mm or height_mm.")
        return self


class FluidicBenchmarkSpec(FluidicModel):
    """Requirements come from the task, never inferred from the candidate itself."""

    required_paths: list[RequiredPath] = Field(default_factory=list)
    expected_flow_rates_ul_min: dict[Identifier, NonNegative] = Field(default_factory=dict)
    required_membranes: list[RequiredMembrane] = Field(default_factory=list)
    expected_channel_count: int | None = Field(
        None, ge=1, strict=True, description="Exact number of all declared channel segments, including feed tubing.",
    )
    channel_dimensions: dict[Identifier, ChannelDimensionConstraints] = Field(
        default_factory=dict, description="External dimension bounds in mm, keyed by required channel ID.",
    )


class FluidicBenchmarkResult(BaseModel):
    """Deterministic per-check scores and actionable failures for one candidate."""

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
    # Preserve the original eight-check score for specifications without these
    # optional requirements; supplied requirements must never be skipped.
    if spec.expected_channel_count is not None:
        checks["channel_count"] = False
    if spec.channel_dimensions:
        checks["channel_dimensions"] = False
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
    outlet_kinds = {outlet.id: outlet.kind for outlet in system.outlets}
    outlet_kinds.update({r.id: "waste" for r in system.reservoirs if r.role == "waste"})
    checks["requested_paths"] = all(
        path.source_id in graph.nodes and path.target_id in graph.nodes
        and path.target_id in reachable(graph.forward, {path.source_id})
        and (path.outlet_kind is None or outlet_kinds.get(path.target_id) == path.outlet_kind)
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
    if spec.expected_channel_count is not None:
        checks["channel_count"] = len(channels) == spec.expected_channel_count
        if not checks["channel_count"]:
            issues.append(FluidicIssue(
                code="requested_channel_count", entity_id="system",
                message=f"Expected {spec.expected_channel_count} channel segments; found {len(channels)}.",
            ))
    if spec.channel_dimensions:
        checks["channel_dimensions"] = True
        for channel_id, dimensions in sorted(spec.channel_dimensions.items()):
            channel = channels.get(channel_id)
            if channel is None:
                checks["channel_dimensions"] = False
                issues.append(FluidicIssue(
                    code="requested_channel_missing", entity_id=channel_id,
                    message="Channel required by dimension constraints is missing.",
                ))
                continue
            for name in ("length_mm", "width_mm", "height_mm"):
                bounds: DimensionRange | None = getattr(dimensions, name)
                value: float = getattr(channel, name)
                if bounds is not None and not bounds.contains(value):
                    checks["channel_dimensions"] = False
                    issues.append(FluidicIssue(
                        code="requested_dimension", entity_id=channel_id,
                        message=(f"{name}={value:g} mm violates inclusive bounds "
                                 f"minimum={bounds.minimum}, maximum={bounds.maximum} mm "
                                 "(None means unbounded)."),
                    ))
    return FluidicBenchmarkResult(
        score=sum(checks.values()) / len(checks), passed=all(checks.values()), checks=checks,
        issues=sorted(issues, key=lambda issue: (issue.code, issue.entity_id, issue.message)),
    )


def main() -> int:
    """Print a benchmark result and exit nonzero when a candidate fails."""
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
