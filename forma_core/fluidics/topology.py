"""Directed bulk-flow graph. Membranes are deliberately not flow edges."""

from __future__ import annotations

from dataclasses import dataclass

from .models import FluidicNode, FluidicSystem


@dataclass(frozen=True)
class FluidicTopology:
    """Node indexes and forward/reverse adjacency for declared bulk-flow edges."""

    nodes: dict[str, FluidicNode]
    sources: set[str]
    sinks: set[str]
    forward: dict[str, set[str]]
    reverse: dict[str, set[str]]


def reachable(adjacency: dict[str, set[str]], starts: set[str]) -> set[str]:
    """Iterative traversal that terminates even for recirculating networks."""
    visited: set[str] = set()
    pending = list(starts)
    while pending:
        current = pending.pop()
        if current not in visited:
            visited.add(current)
            pending.extend(adjacency.get(current, set()) - visited)
    return visited


def build_topology(system: FluidicSystem) -> FluidicTopology:
    """Build indexes without treating unresolved references as real nodes."""
    nodes = {node.id: node for node in [
        *system.inlets, *system.outlets, *system.reservoirs,
        *system.chambers, *system.pumps, *system.valves,
    ]}
    sources = {item.id for item in system.inlets} | {r.id for r in system.reservoirs if r.role == "supply"}
    sinks = {item.id for item in system.outlets} | {r.id for r in system.reservoirs if r.role == "waste"}
    forward: dict[str, set[str]] = {node: set() for node in nodes}
    reverse: dict[str, set[str]] = {node: set() for node in nodes}
    for channel in system.channels:
        if channel.source_id in nodes and channel.target_id in nodes:
            forward[channel.source_id].add(channel.target_id)
            reverse[channel.target_id].add(channel.source_id)
    return FluidicTopology(nodes, sources, sinks, forward, reverse)
