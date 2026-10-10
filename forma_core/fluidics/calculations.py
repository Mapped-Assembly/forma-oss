"""SI-based estimates for rigid, straight, fully developed Newtonian liquid flow.

Rectangular resistance approximation: 12 mu L / (w h^3 (1 - 0.63 h/w)),
where h <= w. See docs/fluidics.md for sources, assumptions and limitations.
"""

from __future__ import annotations

import math

from .models import FluidicChannel, FluidProperties


class FlowCalculationError(ValueError):
    """A calculation is unsupported or lacks required physical inputs."""


def _number(value: float | None, name: str, *, zero: bool = False) -> float:
    if value is None or not math.isfinite(value) or (value < 0 if zero else value <= 0):
        raise FlowCalculationError(f"{name} must be supplied, finite and {'nonnegative' if zero else 'positive'}.")
    return value


def cross_sectional_area_mm2(channel: FluidicChannel) -> float:
    """Rectangular area in mm²."""
    return _number(channel.width_mm, "width_mm") * _number(channel.height_mm, "height_mm")


def channel_volume_ul(channel: FluidicChannel) -> float:
    """Internal channel volume; 1 mm³ = 1 µL."""
    return cross_sectional_area_mm2(channel) * _number(channel.length_mm, "length_mm")


def average_velocity_mm_s(channel: FluidicChannel) -> float:
    """Mean velocity using the supplied target flow (µL/min)."""
    return _number(channel.target_flow_rate_ul_min, "target_flow_rate_ul_min", zero=True) / 60 / cross_sectional_area_mm2(channel)


def residence_time_s(channel: FluidicChannel) -> float:
    """Nominal volume/flow time; zero flow has no finite residence time."""
    return channel_volume_ul(channel) * 60 / _number(channel.target_flow_rate_ul_min, "target_flow_rate_ul_min")


def _liquid_properties(fluid: FluidProperties) -> tuple[float, float]:
    if fluid.phase != "liquid" or not fluid.newtonian:
        raise FlowCalculationError("This estimate requires an incompressible Newtonian liquid.")
    return (
        _number(fluid.dynamic_viscosity_pa_s, "dynamic_viscosity_pa_s"),
        _number(fluid.density_kg_m3, "density_kg_m3"),
    )


def reynolds_number(channel: FluidicChannel, fluid: FluidProperties) -> float:
    """Re based on hydraulic diameter, using explicit viscosity and density."""
    if channel.fluid != fluid.id:
        raise FlowCalculationError(f"Channel fluid '{channel.fluid}' does not match properties '{fluid.id}'.")
    viscosity, density = _liquid_properties(fluid)
    area = cross_sectional_area_mm2(channel)
    diameter_m = 2 * area / (channel.width_mm + channel.height_mm) * 1e-3
    return density * average_velocity_mm_s(channel) * 1e-3 * diameter_m / viscosity


def pressure_drop_kpa(channel: FluidicChannel, fluid: FluidProperties) -> float:
    """Approximate rectangular-channel Δp; reject Re >= 2000 rather than extrapolate."""
    if reynolds_number(channel, fluid) >= 2000:
        raise FlowCalculationError("Laminar estimate requires Reynolds number < 2000.")
    viscosity, _ = _liquid_properties(fluid)
    height, width = sorted((channel.height_mm * 1e-3, channel.width_mm * 1e-3))
    length = _number(channel.length_mm, "length_mm") * 1e-3
    flow = _number(channel.target_flow_rate_ul_min, "target_flow_rate_ul_min", zero=True) * 1e-9 / 60
    return 12 * viscosity * length * flow / (width * height**3 * (1 - 0.63 * height / width)) / 1000


def mean_wall_shear_stress_pa(channel: FluidicChannel, fluid: FluidProperties) -> float:
    """Wetted-perimeter mean Δp A/(L P), not the local cell-surface shear."""
    pressure_pa = pressure_drop_kpa(channel, fluid) * 1000
    area_m2 = cross_sectional_area_mm2(channel) * 1e-6
    perimeter_m = 2 * (channel.width_mm + channel.height_mm) * 1e-3
    return pressure_pa * area_m2 / (channel.length_mm * 1e-3 * perimeter_m)
