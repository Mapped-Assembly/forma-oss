"""Temporary, additive fluid network contract for the organ-on-a-chip MVP."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Identifier = Annotated[str, Field(min_length=1, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")]
Positive = Annotated[float, Field(gt=0, allow_inf_nan=False)]
NonNegative = Annotated[float, Field(ge=0, allow_inf_nan=False)]
Text = Annotated[str, Field(min_length=1)]


class FluidicModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, str_strip_whitespace=True)


class FluidProperties(FluidicModel):
    """Explicit properties at the declared temperature; no water-like defaults."""

    id: Identifier
    phase: Literal["liquid", "gas"] = "liquid"
    dynamic_viscosity_pa_s: Positive | None = None
    density_kg_m3: Positive | None = None
    temperature_c: float | None = None
    newtonian: bool = True
    provenance: Text | None = None


class FluidicNode(FluidicModel):
    id: Identifier
    circuit_id: Identifier = Field("default", description="Bulk-fluid isolation group. Channels cannot cross groups.")


class FluidicInlet(FluidicNode):
    """Boundary source. Every declared inlet requires a path to a sink."""


class FluidicOutlet(FluidicNode):
    kind: Literal["waste", "product", "exhaust"] = "waste"


class FluidicReservoir(FluidicNode):
    volume_ul: Positive
    role: Literal["supply", "junction", "waste"] = "junction"
    contents: Text


class FluidicPump(FluidicNode):
    target_flow_rate_ul_min: NonNegative | None = None
    max_flow_rate_ul_min: NonNegative | None = None


class FluidicValve(FluidicNode):
    """Inline valve in the nominal open flow configuration (no control simulation)."""


class FluidicChannel(FluidicModel):
    id: Identifier
    source_id: Identifier
    target_id: Identifier
    length_mm: Positive
    width_mm: Positive
    height_mm: Positive
    material: Text
    fluid: Text = Field(description="Fluid name; match FluidProperties.id to enable pressure calculations.")
    target_flow_rate_ul_min: NonNegative | None = None
    min_flow_rate_ul_min: NonNegative | None = None
    max_flow_rate_ul_min: NonNegative | None = None
    max_pressure_kpa: Positive | None = Field(None, description="Maximum channel pressure DROP, not absolute pressure.")
    pump_id: Identifier | None = Field(None, description="Optional inline pump; must be a channel endpoint.")
    valve_id: Identifier | None = Field(None, description="Optional inline valve; must be a channel endpoint.")


class FluidicChamber(FluidicNode):
    volume_ul: Positive
    inlet_ids: list[Identifier] = Field(min_length=1, description="All incoming channel IDs, not boundary inlet IDs.")
    outlet_ids: list[Identifier] = Field(min_length=1, description="All outgoing channel IDs.")
    contents: Text
    temperature_c: float | None = None


class FluidicMembrane(FluidicModel):
    """Interface between isolated channels/chambers, never a bulk-flow graph edge."""

    id: Identifier
    side_a_id: Identifier
    side_b_id: Identifier
    material: Text
    thickness_mm: Positive
    pore_size_um: Positive | None = None
    porosity: Annotated[float, Field(gt=0, le=1, allow_inf_nan=False)] | None = None


class FluidicSystem(FluidicModel):
    inlets: list[FluidicInlet] = Field(default_factory=list)
    outlets: list[FluidicOutlet] = Field(default_factory=list)
    reservoirs: list[FluidicReservoir] = Field(default_factory=list)
    channels: list[FluidicChannel] = Field(default_factory=list)
    chambers: list[FluidicChamber] = Field(default_factory=list)
    pumps: list[FluidicPump] = Field(default_factory=list)
    valves: list[FluidicValve] = Field(default_factory=list)
    membranes: list[FluidicMembrane] = Field(default_factory=list)
    fluids: list[FluidProperties] = Field(default_factory=list)

    @model_validator(mode="after")
    def unique_ids(self) -> FluidicSystem:
        seen: set[str] = set()
        for collection in type(self).model_fields:
            for entity in getattr(self, collection):
                if entity.id in seen:
                    raise ValueError(f"Duplicate fluidic ID '{entity.id}'.")
                seen.add(entity.id)
        return self
