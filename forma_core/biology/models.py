"""Typed biological experiment metadata that composes with Forma fluidic systems.

The models in this module describe experimental intent, provenance, sampling and
observations. They deliberately do not implement a toxicity predictor, biological
simulator or clinical decision system.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Identifier = Annotated[str, Field(min_length=1, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")]
NonNegative = Annotated[float, Field(ge=0, allow_inf_nan=False)]
Positive = Annotated[float, Field(gt=0, allow_inf_nan=False)]
Text = Annotated[str, Field(min_length=1)]
Probability = Annotated[float, Field(ge=0, le=1, allow_inf_nan=False)]


class BiologyModel(BaseModel):
    """Shared strict-field and finite-number contract for biological metadata."""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, str_strip_whitespace=True)


class DatasetReference(BiologyModel):
    """Provenance record for a dataset, publication or external evidence source."""

    id: Identifier
    name: Text
    kind: Literal["reference_outcomes", "imaging", "omics", "assay", "literature", "other"] = "other"
    uri: Text
    version: Text | None = None
    license: Text | None = None
    citation: Text | None = None
    notes: Text | None = None


class BiologicalCompartment(BiologyModel):
    """Biological region mapped to one or more physical fluidic components."""

    id: Identifier
    role: Literal["tissue", "vascular", "support", "control", "other"] = "tissue"
    cell_types: list[Text] = Field(min_length=1)
    fluidic_component_ids: list[Identifier] = Field(
        default_factory=list,
        description="Fluidic channel/chamber IDs that physically host or expose this compartment.",
    )
    donor_or_source: Text | None = None
    notes: Text | None = None


class CompoundExposure(BiologyModel):
    """Declared compound exposure; concentrations are metadata, not dose recommendations."""

    id: Identifier
    compound_name: Text
    compound_identifier: Text | None = Field(
        None,
        description="Optional external identifier such as a PubChem CID or project-local compound ID.",
    )
    compartment_id: Identifier
    concentration_value: Positive
    concentration_unit: Text
    start_time_h: NonNegative = 0
    duration_h: Positive
    vehicle: Text | None = None
    schedule: Text | None = None
    dataset_ref_ids: list[Identifier] = Field(default_factory=list)
    notes: Text | None = None


class ExperimentalControl(BiologyModel):
    """Control arm metadata for comparison with one or more biological compartments."""

    id: Identifier
    kind: Literal["vehicle", "untreated", "positive", "negative", "reference"]
    compartment_ids: list[Identifier] = Field(min_length=1)
    description: Text
    dataset_ref_ids: list[Identifier] = Field(default_factory=list)


class BiologicalEndpoint(BiologyModel):
    """Planned biological measurement or derived phenotype."""

    id: Identifier
    name: Text
    measurement_type: Literal["viability", "injury", "function", "imaging", "omics", "biomarker", "other"]
    unit: Text | None = None
    description: Text | None = None
    dataset_ref_ids: list[Identifier] = Field(default_factory=list)


class SamplingPoint(BiologyModel):
    """Planned sampling time for a compartment and one or more endpoints."""

    id: Identifier
    time_h: NonNegative
    compartment_id: Identifier
    endpoint_ids: list[Identifier] = Field(min_length=1)
    notes: Text | None = None


class BiologicalObservation(BiologyModel):
    """Observed or imported measurement with mandatory source provenance."""

    id: Identifier
    endpoint_id: Identifier
    compartment_id: Identifier
    time_h: NonNegative
    numeric_value: float | None = Field(None, allow_inf_nan=False)
    categorical_value: Text | None = None
    unit: Text | None = None
    dataset_ref_id: Identifier
    source_record_id: Text | None = None
    notes: Text | None = None

    @model_validator(mode="after")
    def exactly_one_value(self) -> "BiologicalObservation":
        """Require one unambiguous observed value representation."""
        values = (self.numeric_value is not None, self.categorical_value is not None)
        if sum(values) != 1:
            raise ValueError("BiologicalObservation requires exactly one numeric_value or categorical_value.")
        return self


class ReferenceOutcome(BiologyModel):
    """External ground-truth/reference label kept separate from model predictions."""

    id: Identifier
    subject: Text = Field(description="Compound, sample or experimental subject described by the outcome.")
    outcome_type: Literal["dili_label", "severity", "phenotype", "assay_result", "other"]
    value: Text
    dataset_ref_id: Identifier
    confidence: Probability | None = None
    source_record_id: Text | None = None
    notes: Text | None = None


class BiologicalExperiment(BiologyModel):
    """Auditable biological study metadata layered on a physical experimental system."""

    id: Identifier
    name: Text
    organ_model: Text
    purpose: Text
    compartments: list[BiologicalCompartment] = Field(min_length=1)
    exposures: list[CompoundExposure] = Field(default_factory=list)
    controls: list[ExperimentalControl] = Field(default_factory=list)
    endpoints: list[BiologicalEndpoint] = Field(min_length=1)
    sampling_points: list[SamplingPoint] = Field(default_factory=list)
    datasets: list[DatasetReference] = Field(default_factory=list)
    observations: list[BiologicalObservation] = Field(default_factory=list)
    reference_outcomes: list[ReferenceOutcome] = Field(default_factory=list)
    limitations: list[Text] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_internal_references(self) -> "BiologicalExperiment":
        """Reject duplicate IDs and unresolved references inside the biological layer."""
        collections = (
            self.compartments,
            self.exposures,
            self.controls,
            self.endpoints,
            self.sampling_points,
            self.datasets,
            self.observations,
            self.reference_outcomes,
        )
        seen: set[str] = set()
        for collection in collections:
            for entity in collection:
                if entity.id in seen:
                    raise ValueError(f"Duplicate biological ID '{entity.id}'.")
                seen.add(entity.id)

        compartment_ids = {item.id for item in self.compartments}
        endpoint_ids = {item.id for item in self.endpoints}
        dataset_ids = {item.id for item in self.datasets}

        for exposure in self.exposures:
            self._require_reference("exposure", exposure.id, "compartment", exposure.compartment_id, compartment_ids)
            for dataset_id in exposure.dataset_ref_ids:
                self._require_reference("exposure", exposure.id, "dataset", dataset_id, dataset_ids)

        for control in self.controls:
            for compartment_id in control.compartment_ids:
                self._require_reference("control", control.id, "compartment", compartment_id, compartment_ids)
            for dataset_id in control.dataset_ref_ids:
                self._require_reference("control", control.id, "dataset", dataset_id, dataset_ids)

        for endpoint in self.endpoints:
            for dataset_id in endpoint.dataset_ref_ids:
                self._require_reference("endpoint", endpoint.id, "dataset", dataset_id, dataset_ids)

        for sampling_point in self.sampling_points:
            self._require_reference(
                "sampling point", sampling_point.id, "compartment", sampling_point.compartment_id, compartment_ids
            )
            for endpoint_id in sampling_point.endpoint_ids:
                self._require_reference("sampling point", sampling_point.id, "endpoint", endpoint_id, endpoint_ids)

        for observation in self.observations:
            self._require_reference("observation", observation.id, "endpoint", observation.endpoint_id, endpoint_ids)
            self._require_reference(
                "observation", observation.id, "compartment", observation.compartment_id, compartment_ids
            )
            self._require_reference(
                "observation", observation.id, "dataset", observation.dataset_ref_id, dataset_ids
            )

        for outcome in self.reference_outcomes:
            self._require_reference("reference outcome", outcome.id, "dataset", outcome.dataset_ref_id, dataset_ids)

        return self

    @staticmethod
    def _require_reference(
        owner_kind: str,
        owner_id: str,
        target_kind: str,
        target_id: str,
        valid_ids: set[str],
    ) -> None:
        """Raise a consistent validation error for an unresolved internal reference."""
        if target_id not in valid_ids:
            raise ValueError(
                f"Biological {owner_kind} '{owner_id}' references unknown {target_kind} '{target_id}'."
            )
