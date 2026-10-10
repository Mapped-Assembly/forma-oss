"""Milestone-scoped fluidics support; independent of electrical/mechanical IR."""

from .models import FluidicSystem
from .validation import FluidicIssue, validate_fluidic_system

__all__ = ["FluidicSystem", "FluidicIssue", "validate_fluidic_system"]
