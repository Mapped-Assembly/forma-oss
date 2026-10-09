"""Reproducible organ-chip fixture; values are declared demonstration inputs."""

from .models import (
    FluidicChannel, FluidicChamber, FluidicInlet, FluidicMembrane,
    FluidicOutlet, FluidicPump, FluidicSystem, FluidicValve, FluidProperties,
)


def organ_on_chip_system(*, dosing: bool = False) -> FluidicSystem:
    """Two liquid circuits with separate waste outlets and a porous interface.

    Optional dosing joins the vascular chamber only. It adds 5 µL/min to the
    downstream vascular channel; the independent epithelial circuit is unchanged.
    """
    system = FluidicSystem(fluids=[FluidProperties(
        id="demo_medium", dynamic_viscosity_pa_s=0.001, density_kg_m3=1000,
        temperature_c=22, provenance="Illustrative water-like inputs at 22 C; not measured culture-medium data.",
    )])
    for circuit, flow in [("vascular", 30.0), ("epithelial", 10.0)]:
        inlet, pump, chamber, waste = [f"{circuit}_{suffix}" for suffix in ("inlet", "pump", "chamber", "waste")]
        system.inlets.append(FluidicInlet(id=inlet, circuit_id=circuit))
        system.pumps.append(FluidicPump(id=pump, circuit_id=circuit, target_flow_rate_ul_min=flow, max_flow_rate_ul_min=60))
        system.chambers.append(FluidicChamber(
            id=chamber, circuit_id=circuit, volume_ul=2, inlet_ids=[f"{circuit}_feed"],
            outlet_ids=[f"{circuit}_channel"], contents=f"{circuit.title()} perfusion distribution chamber", temperature_c=22,
        ))
        system.outlets.append(FluidicOutlet(id=waste, circuit_id=circuit))
        for suffix, source, target, length in [
            ("supply", inlet, pump, 5), ("feed", pump, chamber, 5), ("channel", chamber, waste, 20),
        ]:
            system.channels.append(FluidicChannel(
                id=f"{circuit}_{suffix}", source_id=source, target_id=target,
                length_mm=length, width_mm=1, height_mm=0.2, material="PDMS", fluid="demo_medium",
                target_flow_rate_ul_min=flow, max_flow_rate_ul_min=60, max_pressure_kpa=5,
                pump_id=pump if pump in (source, target) else None,
            ))
    system.membranes.append(FluidicMembrane(
        id="porous_interface", side_a_id="vascular_channel", side_b_id="epithelial_channel",
        material="porous PET", thickness_mm=0.01, pore_size_um=0.4, porosity=0.1,
    ))
    if dosing:
        system.inlets.append(FluidicInlet(id="dose_inlet", circuit_id="vascular"))
        system.valves.append(FluidicValve(id="dose_valve", circuit_id="vascular"))
        for name, source, target in [
            ("dose_supply", "dose_inlet", "dose_valve"),
            ("dose_channel", "dose_valve", "vascular_chamber"),
        ]:
            system.channels.append(FluidicChannel(
                id=name, source_id=source, target_id=target, length_mm=5, width_mm=1, height_mm=0.2,
                material="PDMS", fluid="demo_medium", target_flow_rate_ul_min=5, valve_id="dose_valve",
            ))
        system.chambers[0].inlet_ids.append("dose_channel")
        next(c for c in system.channels if c.id == "vascular_channel").target_flow_rate_ul_min = 35
    return FluidicSystem.model_validate(system.model_dump())
