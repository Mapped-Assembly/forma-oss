"""Deterministic topology and supplied operating-constraint checks."""

from __future__ import annotations

from math import isclose

from pydantic import BaseModel, ValidationError

from .calculations import FlowCalculationError, pressure_drop_kpa
from .models import FluidicSystem
from .topology import build_topology, reachable


class FluidicIssue(BaseModel):
    """Blocking finding with a stable code, component ID or schema location."""

    code: str
    entity_id: str
    message: str


def validate_fluidic_system(system: FluidicSystem) -> list[FluidicIssue]:
    """Return blocking findings. An empty result means supplied checks passed.

    This checks nominal open-valve topology, not valve sequencing, pressure
    balancing, transport across membranes, biology, or fabrication readiness.
    """
    issues: list[FluidicIssue] = []

    def add(code: str, entity_id: str, message: str) -> None:
        issues.append(FluidicIssue(code=code, entity_id=entity_id, message=message))

    # Lists/models are mutable: recheck dimensions and IDs after in-process edits.
    try:
        system = FluidicSystem.model_validate(system.model_dump())
    except ValidationError as exc:
        return [FluidicIssue(
            code="schema", entity_id=".".join(map(str, error["loc"])) or "system", message=error["msg"],
        ) for error in exc.errors()]

    graph = build_topology(system)
    channels = {item.id: item for item in system.channels}
    pumps = {item.id: item for item in system.pumps}
    valves = {item.id: item for item in system.valves}
    fluids = {item.id: item for item in system.fluids}
    if not graph.sources:
        add("missing_source", "system", "Declare at least one inlet or supply reservoir.")
    if not graph.sinks:
        add("missing_outlet", "system", "Declare at least one outlet or waste reservoir.")
    if not channels:
        add("missing_channel", "system", "Declare at least one flow channel.")
    for channel in system.channels:
        source, target = graph.nodes.get(channel.source_id), graph.nodes.get(channel.target_id)
        for endpoint in (channel.source_id, channel.target_id):
            if endpoint not in graph.nodes:
                add("unknown_node", channel.id, f"Unknown channel endpoint '{endpoint}'.")
        if channel.source_id == channel.target_id or channel.target_id in graph.sources or channel.source_id in graph.sinks:
            add("invalid_direction", channel.id, "Channels cannot self-connect, enter a source or leave a sink.")
        if source and target and source.circuit_id != target.circuit_id:
            add("circuit_mixing", channel.id, "Bulk flow cannot cross isolated circuit IDs; use a membrane interface.")
        for reference, catalog, kind in [(channel.pump_id, pumps, "pump"), (channel.valve_id, valves, "valve")]:
            if reference is not None:
                if reference not in catalog:
                    add(f"unknown_{kind}", channel.id, f"Unknown {kind} '{reference}'.")
                elif reference not in (channel.source_id, channel.target_id):
                    add(f"non_inline_{kind}", channel.id, f"Referenced {kind} '{reference}' must be a channel endpoint.")
        lower, upper, flow = channel.min_flow_rate_ul_min, channel.max_flow_rate_ul_min, channel.target_flow_rate_ul_min
        if lower is not None and upper is not None and lower > upper:
            add("flow_bounds", channel.id, "Minimum flow exceeds maximum flow.")
        if (lower is not None or upper is not None) and flow is None:
            add("flow_unknown", channel.id, "A flow target is required to check the supplied bounds.")
        if flow is not None and ((lower is not None and flow < lower) or (upper is not None and flow > upper)):
            add("flow_bounds", channel.id, "Target flow is outside the declared bounds.")
        if channel.max_pressure_kpa is not None:
            try:
                if channel.fluid not in fluids:
                    raise FlowCalculationError(f"Missing properties for fluid '{channel.fluid}'.")
                drop = pressure_drop_kpa(channel, fluids[channel.fluid])
                if drop > channel.max_pressure_kpa:
                    add("pressure_limit", channel.id, f"Estimated pressure drop {drop:.6g} kPa exceeds the declared limit.")
            except FlowCalculationError as exc:
                add("pressure_unknown", channel.id, str(exc))

    from_source = reachable(graph.forward, graph.sources)
    to_sink = reachable(graph.reverse, graph.sinks)
    for node_id in sorted(graph.nodes):
        if node_id not in from_source:
            add("unreachable_node", node_id, "Node has no incoming path from a source.")
        if node_id not in to_sink:
            add("no_outlet_path", node_id, "Node cannot reach a valid outlet or waste reservoir.")

    incoming = {node: [c for c in system.channels if c.target_id == node] for node in graph.nodes}
    outgoing = {node: [c for c in system.channels if c.source_id == node] for node in graph.nodes}
    for chamber in system.chambers:
        for declared, actual, label in [
            (chamber.inlet_ids, incoming[chamber.id], "inlet_ids"),
            (chamber.outlet_ids, outgoing[chamber.id], "outlet_ids"),
        ]:
            if len(declared) != len(set(declared)) or set(declared) != {c.id for c in actual}:
                add("chamber_ports", chamber.id, f"{label} must list exactly the connected {label.split('_')[0]} channel IDs.")

    for node_id in sorted(graph.nodes.keys() - graph.sources - graph.sinks):
        ins, outs = incoming[node_id], outgoing[node_id]
        flows = [c.target_flow_rate_ul_min for c in ins + outs]
        if ins and outs and all(q is not None for q in flows):
            inflow = sum(c.target_flow_rate_ul_min for c in ins)
            outflow = sum(c.target_flow_rate_ul_min for c in outs)
            if not isclose(inflow, outflow, rel_tol=1e-6, abs_tol=1e-9):
                add("flow_balance", node_id, "Supplied flows do not conserve volume at this steady-state internal node.")
        pump = pumps.get(node_id)
        if pump is not None:
            target, maximum = pump.target_flow_rate_ul_min, pump.max_flow_rate_ul_min
            if target is not None and maximum is not None and target > maximum:
                add("pump_flow_limit", node_id, "Pump target exceeds pump capacity.")
            for adjacent in (ins, outs):
                if not adjacent or any(c.target_flow_rate_ul_min is None for c in adjacent):
                    if target is not None or maximum is not None:
                        add("pump_flow_unknown", node_id, "Supply adjacent channel flows to verify the pump target/capacity.")
                    continue
                total = sum(c.target_flow_rate_ul_min for c in adjacent)
                if target is not None and not isclose(total, target, rel_tol=1e-6, abs_tol=1e-9):
                    add("pump_flow_target", node_id, "Adjacent channel flow does not match the pump target.")
                if maximum is not None and total > maximum:
                    add("pump_flow_limit", node_id, "Adjacent channel flow exceeds pump capacity.")

    interface_circuits = {c.id: graph.nodes[c.source_id].circuit_id for c in system.channels if c.source_id in graph.nodes}
    interface_circuits.update({c.id: c.circuit_id for c in system.chambers})
    for membrane in system.membranes:
        sides = [interface_circuits.get(membrane.side_a_id), interface_circuits.get(membrane.side_b_id)]
        if None in sides:
            add("membrane_reference", membrane.id, "Each membrane side must reference an existing channel or chamber.")
        elif sides[0] == sides[1]:
            add("membrane_isolation", membrane.id, "Membrane sides must belong to distinct bulk-fluid circuits.")
    return sorted(issues, key=lambda issue: (issue.code, issue.entity_id, issue.message))
