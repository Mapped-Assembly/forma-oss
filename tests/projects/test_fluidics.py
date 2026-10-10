from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import unittest

from pydantic import ValidationError

from forma_core.fluidics.benchmark import (
    ChannelDimensionConstraints, DimensionRange, FluidicBenchmarkSpec, score_fluidic_system,
)
from forma_core.fluidics.calculations import (
    FlowCalculationError, average_velocity_mm_s, channel_volume_ul,
    cross_sectional_area_mm2, mean_wall_shear_stress_pa, pressure_drop_kpa,
    residence_time_s, reynolds_number,
)
from forma_core.fluidics.examples import organ_on_chip_system
from forma_core.fluidics.models import (
    FluidicChannel, FluidicInlet, FluidicOutlet, FluidicReservoir, FluidicSystem, FluidicValve,
)
from forma_core.fluidics.validation import validate_fluidic_system
from forma_core.validation import validate_project
from forma_core.workspaces.projects.models import HardwareIntermediateRepresentation

ROOT = Path(__file__).resolve().parents[2]
EXAMPLES = ROOT / "examples" / "organ-on-chip"


class FluidicTests(unittest.TestCase):
    def setUp(self):
        self.system = organ_on_chip_system()
        self.spec = FluidicBenchmarkSpec.model_validate_json((EXAMPLES / "two-channel-spec.json").read_text())

    def codes(self):
        return {issue.code for issue in validate_fluidic_system(self.system)}

    def test_valid_two_channel_and_dosing_networks(self):
        for dosing in (False, True):
            with self.subTest(dosing=dosing):
                self.assertEqual([], validate_fluidic_system(organ_on_chip_system(dosing=dosing)))

    def test_basic_inlet_channel_outlet_without_fluid_properties(self) -> None:
        system = FluidicSystem(
            inlets=[FluidicInlet(id="inlet")], outlets=[FluidicOutlet(id="waste")],
            channels=[FluidicChannel(
                id="channel", source_id="inlet", target_id="waste", length_mm=20,
                width_mm=1, height_mm=0.2, material="PDMS", fluid="unspecified medium",
            )],
        )
        self.assertEqual([], validate_fluidic_system(system))
        self.assertEqual(system, FluidicSystem.model_validate_json(system.model_dump_json()))

    def test_missing_endpoints_identify_channel_and_missing_node(self) -> None:
        for endpoint in ("source_id", "target_id"):
            with self.subTest(endpoint=endpoint):
                system = organ_on_chip_system()
                setattr(system.channels[0], endpoint, "missing_node")
                issues = validate_fluidic_system(system)
                self.assertTrue(any(
                    issue.code == "unknown_node" and issue.entity_id == "vascular_supply"
                    and "missing_node" in issue.message for issue in issues
                ))

    def test_disconnected_required_inlet_and_orphan_valve(self) -> None:
        self.system.inlets.append(FluidicInlet(id="disconnected_inlet"))
        self.system.valves.append(FluidicValve(id="orphan_valve"))
        failures = {(issue.code, issue.entity_id) for issue in validate_fluidic_system(self.system)}
        self.assertIn(("no_outlet_path", "disconnected_inlet"), failures)
        self.assertIn(("unreachable_node", "orphan_valve"), failures)
        self.assertIn(("no_outlet_path", "orphan_valve"), failures)

    def test_ir_round_trip_and_backward_compatibility(self):
        legacy = HardwareIntermediateRepresentation.model_validate({"hardware_ir_version": "0.1"})
        self.assertIsNone(legacy.fluidic_system)
        self.assertEqual([], validate_project(legacy))
        project = HardwareIntermediateRepresentation(fluidic_system=self.system)
        self.assertEqual(project, HardwareIntermediateRepresentation.model_validate_json(project.model_dump_json()))
        schema = HardwareIntermediateRepresentation.model_json_schema()
        self.assertIn("FluidicSystem", schema["$defs"])
        self.assertNotIn("fluidic_system", schema.get("required", []))

    def test_invalid_dimensions_and_nonfinite_values(self):
        for field in ("length_mm", "width_mm", "height_mm"):
            for value in (0, -1, float("nan"), float("inf")):
                with self.subTest(field=field, value=value):
                    payload = self.system.model_dump()
                    payload["channels"][0][field] = value
                    with self.assertRaises(ValidationError):
                        FluidicSystem.model_validate(payload)

    def test_duplicate_ids_across_entity_types(self):
        self.system.pumps[0].id = self.system.inlets[0].id
        with self.assertRaisesRegex(ValidationError, "Duplicate fluidic ID"):
            FluidicSystem.model_validate(self.system.model_dump())
        self.assertIn("schema", self.codes())

    def test_unknown_node(self):
        self.system.channels[0].source_id = "missing_source"
        self.assertIn("unknown_node", self.codes())
        self.assertIn("unreachable_node", self.codes())

    def test_missing_outlets_and_dead_end_branch(self):
        self.system.outlets.clear()
        self.assertIn("missing_outlet", self.codes())
        self.assertIn("no_outlet_path", self.codes())
        self.system = organ_on_chip_system()
        self.system.reservoirs.append(FluidicReservoir(id="dead_end", circuit_id="vascular", volume_ul=1, contents="medium"))
        branch = self.system.channels[2].model_copy(update={"id": "dead_branch", "target_id": "dead_end"})
        self.system.channels.append(branch)
        self.assertIn("no_outlet_path", self.codes())

    def test_disconnected_cycle_does_not_hang_or_pass(self):
        for name in ("orphan_a", "orphan_b"):
            self.system.reservoirs.append(FluidicReservoir(id=name, volume_ul=1, contents="medium"))
        for source, target in [("orphan_a", "orphan_b"), ("orphan_b", "orphan_a")]:
            self.system.channels.append(self.system.channels[2].model_copy(update={
                "id": source + "_edge", "source_id": source, "target_id": target,
            }))
        self.assertIn("unreachable_node", self.codes())
        self.assertIn("no_outlet_path", self.codes())

    def test_invalid_source_source_outlet_outlet_and_self_edges(self):
        for source, target in [("vascular_inlet", "epithelial_inlet"),
                               ("vascular_waste", "epithelial_waste"),
                               ("vascular_pump", "vascular_pump")]:
            with self.subTest(source=source, target=target):
                self.system.channels[0].source_id = source
                self.system.channels[0].target_id = target
                self.assertIn("invalid_direction", self.codes())

    def test_pump_and_valve_references_must_exist_and_be_inline(self):
        for field, missing, unrelated in [("pump_id", "unknown_pump", "non_inline_pump"),
                                          ("valve_id", "unknown_valve", "non_inline_valve")]:
            self.system = organ_on_chip_system(dosing=True)
            setattr(self.system.channels[2], field, "missing")
            self.assertIn(missing, self.codes())
            setattr(self.system.channels[2], field, "epithelial_pump" if field == "pump_id" else "dose_valve")
            self.assertIn(unrelated, self.codes())

    def test_chamber_ports_are_exact_incident_channel_ids(self):
        self.system.chambers[0].inlet_ids = ["epithelial_feed"]
        self.assertIn("chamber_ports", self.codes())
        self.system.chambers[0].inlet_ids = ["vascular_feed", "vascular_feed"]
        self.assertIn("chamber_ports", self.codes())

    def test_accidental_mixing_is_rejected(self):
        self.system.channels[2].target_id = "epithelial_chamber"
        self.assertIn("circuit_mixing", self.codes())
        self.assertFalse(score_fluidic_system(self.system, self.spec).checks["isolation"])

    def test_membrane_references_and_isolation(self):
        self.system.membranes[0].side_b_id = "missing"
        self.assertIn("membrane_reference", self.codes())
        self.system.membranes[0].side_b_id = "vascular_chamber"
        self.assertIn("membrane_isolation", self.codes())

    def test_flow_bounds_balance_and_pump_capacity(self):
        channel = self.system.channels[0]
        channel.min_flow_rate_ul_min = 50
        channel.max_flow_rate_ul_min = 40
        self.assertIn("flow_bounds", self.codes())
        channel.target_flow_rate_ul_min = None
        self.assertIn("flow_unknown", self.codes())
        self.assertIn("pump_flow_unknown", self.codes())
        channel.target_flow_rate_ul_min = 70
        self.assertIn("flow_balance", self.codes())
        self.assertIn("pump_flow_limit", self.codes())
        self.assertIn("pump_flow_target", self.codes())

    def test_negative_nonfinite_flows_rejected(self):
        for value in (-1, float("nan"), float("inf")):
            payload = self.system.model_dump()
            payload["channels"][0]["target_flow_rate_ul_min"] = value
            with self.assertRaises(ValidationError):
                FluidicSystem.model_validate(payload)

    def test_pressure_limit_and_missing_properties(self):
        self.system.channels[0].max_pressure_kpa = 0.0001
        self.assertIn("pressure_limit", self.codes())
        self.system.fluids.clear()
        self.assertIn("pressure_unknown", self.codes())
        for channel in self.system.channels:
            channel.max_pressure_kpa = None
        self.assertEqual([], validate_fluidic_system(self.system))

    def test_waste_reservoir_is_valid_terminal(self):
        self.system.outlets = self.system.outlets[1:]
        self.system.reservoirs.append(FluidicReservoir(
            id="vascular_waste", circuit_id="vascular", role="waste", volume_ul=1000, contents="waste",
        ))
        self.assertEqual([], validate_fluidic_system(self.system))
        self.assertTrue(score_fluidic_system(self.system, self.spec).passed)

    def test_calculation_units_against_hand_values(self):
        channel = self.system.channels[2]  # 20 x 1 x 0.2 mm, 30 uL/min
        fluid = self.system.fluids[0]
        self.assertAlmostEqual(0.2, cross_sectional_area_mm2(channel))
        self.assertAlmostEqual(4, channel_volume_ul(channel))
        self.assertAlmostEqual(2.5, average_velocity_mm_s(channel))
        self.assertAlmostEqual(8, residence_time_s(channel))
        self.assertAlmostEqual(5 / 6, reynolds_number(channel, fluid))
        self.assertAlmostEqual(0.017162471395881, pressure_drop_kpa(channel, fluid))
        self.assertAlmostEqual(0.0715102974828375, mean_wall_shear_stress_pa(channel, fluid))
        channel.width_mm, channel.height_mm = channel.height_mm, channel.width_mm
        self.assertAlmostEqual(0.017162471395881, pressure_drop_kpa(channel, fluid))

    def test_unsupported_calculations_fail_clearly(self):
        channel, fluid = self.system.channels[2], self.system.fluids[0]
        for update in ({"dynamic_viscosity_pa_s": None}, {"density_kg_m3": None},
                       {"phase": "gas"}, {"newtonian": False}, {"id": "wrong_fluid"}):
            with self.subTest(update=update), self.assertRaises(FlowCalculationError):
                pressure_drop_kpa(channel, fluid.model_copy(update=update))
        channel.target_flow_rate_ul_min = 100000
        with self.assertRaisesRegex(FlowCalculationError, "Reynolds"):
            pressure_drop_kpa(channel, fluid)
        channel.target_flow_rate_ul_min = 0
        self.assertEqual(0, average_velocity_mm_s(channel))
        self.assertEqual(0, pressure_drop_kpa(channel, fluid))
        with self.assertRaises(FlowCalculationError):
            residence_time_s(channel)
        channel.target_flow_rate_ul_min = None
        with self.assertRaises(FlowCalculationError):
            average_velocity_mm_s(channel)

    def test_benchmark_requires_external_requirements_not_only_valid_graph(self):
        result = score_fluidic_system(self.system, self.spec)
        self.assertTrue(result.passed)
        self.assertEqual(1, result.score)
        self.assertEqual(result, score_fluidic_system(self.system, self.spec))
        changed = self.spec.model_copy(deep=True)
        changed.expected_flow_rates_ul_min["vascular_channel"] = 40
        self.assertFalse(score_fluidic_system(self.system, changed).checks["requested_flows"])
        self.system.membranes.clear()
        self.assertFalse(score_fluidic_system(self.system, self.spec).checks["membranes"])
        self.system.outlets[0].kind = "product"
        self.assertFalse(score_fluidic_system(self.system, self.spec).checks["requested_paths"])

    def test_benchmark_channel_count_includes_feed_segments(self) -> None:
        self.assertEqual(6, self.spec.expected_channel_count)
        self.assertTrue(score_fluidic_system(self.system, self.spec).checks["channel_count"])
        spec = self.spec.model_copy(deep=True)
        spec.expected_channel_count = 7
        result = score_fluidic_system(self.system, spec)
        self.assertFalse(result.passed)
        self.assertTrue(result.checks["topology"])
        self.assertFalse(result.checks["channel_count"])
        self.assertEqual(0.9, result.score)
        finding = next(issue for issue in result.issues if issue.code == "requested_channel_count")
        self.assertEqual("system", finding.entity_id)
        self.assertIn("Expected 7 channel segments; found 6", finding.message)

    def test_benchmark_dimension_ranges_reject_valid_but_wrong_designs(self) -> None:
        for field, lower, upper in [("length_mm", 19, 21), ("width_mm", 0.9, 1.1), ("height_mm", 0.18, 0.22)]:
            for value, expected in [(lower, True), (upper, True), (lower * 0.99, False), (upper * 1.01, False)]:
                with self.subTest(field=field, value=value):
                    system = organ_on_chip_system()
                    setattr(system.channels[2], field, value)
                    self.assertEqual([], validate_fluidic_system(system))
                    result = score_fluidic_system(system, self.spec)
                    self.assertEqual(expected, result.checks["channel_dimensions"])
                    self.assertEqual(expected, result.passed)
                    if not expected:
                        finding = next(issue for issue in result.issues if issue.code == "requested_dimension")
                        self.assertEqual("vascular_channel", finding.entity_id)
                        self.assertIn(field, finding.message)
        self.system.channels[2].width_mm = 1000
        self.assertFalse(score_fluidic_system(self.system, self.spec).passed)

    def test_benchmark_one_sided_ranges_and_missing_constrained_channel(self) -> None:
        spec = self.spec.model_copy(deep=True)
        spec.channel_dimensions = {
            "vascular_channel": ChannelDimensionConstraints(
                width_mm=DimensionRange(minimum=1), height_mm=DimensionRange(maximum=0.2),
            ),
        }
        self.assertTrue(score_fluidic_system(self.system, spec).passed)
        spec.channel_dimensions["missing_channel"] = ChannelDimensionConstraints(
            length_mm=DimensionRange(minimum=1),
        )
        result = score_fluidic_system(self.system, spec)
        self.assertFalse(result.checks["channel_dimensions"])
        self.assertTrue(any(
            issue.code == "requested_channel_missing" and issue.entity_id == "missing_channel"
            for issue in result.issues
        ))

    def test_benchmark_specs_reject_invalid_ranges_and_counts(self) -> None:
        for bounds in ({}, {"minimum": 2, "maximum": 1}, {"minimum": 0}, {"maximum": -1},
                       {"minimum": float("nan")}, {"maximum": float("inf")}):
            with self.subTest(bounds=bounds), self.assertRaises(ValidationError):
                DimensionRange.model_validate(bounds)
        with self.assertRaises(ValidationError):
            ChannelDimensionConstraints.model_validate({})
        for value in (0, -1, 2.5, True, "6"):
            payload = self.spec.model_dump()
            payload["expected_channel_count"] = value
            with self.subTest(value=value), self.assertRaises(ValidationError):
                FluidicBenchmarkSpec.model_validate(payload)
        self.assertEqual(self.spec, FluidicBenchmarkSpec.model_validate_json(self.spec.model_dump_json()))

    def test_legacy_benchmark_specs_keep_original_eight_checks(self) -> None:
        payload = self.spec.model_dump(exclude={"expected_channel_count", "channel_dimensions"})
        spec = FluidicBenchmarkSpec.model_validate(payload)
        result = score_fluidic_system(self.system, spec)
        self.assertTrue(result.passed)
        self.assertEqual(1, result.score)
        self.assertEqual(8, len(result.checks))
        self.assertNotIn("channel_count", result.checks)
        self.assertNotIn("channel_dimensions", result.checks)

    def test_raw_generated_and_validated_candidates_use_same_external_spec(self) -> None:
        raw = self.system.model_dump(mode="json")
        unvalidated = HardwareIntermediateRepresentation(fluidic_system=self.system).model_dump(mode="json")
        validated = HardwareIntermediateRepresentation.model_validate(unvalidated)
        self.assertEqual([], validate_project(validated))
        expected = score_fluidic_system(raw, self.spec)
        for payload in (unvalidated, validated.model_dump(mode="json")):
            self.assertEqual(expected, score_fluidic_system(payload, self.spec))

    def test_fault_injection_and_external_repair_are_deterministic(self) -> None:
        original = self.system.model_dump(mode="json")
        for fault in ("remove_outlet", "reverse_connection", "zero_width", "unknown_node", "remove_pump", "duplicate_id"):
            with self.subTest(fault=fault):
                payload = json.loads(json.dumps(original))
                channel = payload["channels"][0]
                if fault == "remove_outlet":
                    payload["outlets"].pop(0)
                elif fault == "reverse_connection":
                    channel["source_id"], channel["target_id"] = channel["target_id"], channel["source_id"]
                elif fault == "zero_width":
                    channel["width_mm"] = 0
                elif fault == "unknown_node":
                    channel["target_id"] = "missing_node"
                elif fault == "remove_pump":
                    payload["pumps"].pop(0)
                else:
                    payload["channels"].append(dict(channel))
                result = score_fluidic_system(payload, self.spec)
                self.assertFalse(result.passed)
                self.assertTrue(result.issues or result.schema_errors)
                self.assertEqual(result, score_fluidic_system(payload, self.spec))
                self.assertTrue(score_fluidic_system(original, self.spec).passed)

    def test_empty_missing_and_malformed_networks_cannot_pass(self):
        for payload in ({}, None, {"fluidic_system": None}, {"channels": [{"length_mm": -1}]}):
            with self.subTest(payload=payload):
                self.assertFalse(score_fluidic_system(payload, self.spec).passed)

    def test_all_committed_examples_and_benchmark_cli(self):
        for name in ("two-channel", "with-dosing"):
            spec = FluidicBenchmarkSpec.model_validate_json((EXAMPLES / f"{name}-spec.json").read_text())
            payload = json.loads((EXAMPLES / f"{name}.json").read_text())
            self.assertTrue(score_fluidic_system(payload, spec).passed)
        result = subprocess.run([sys.executable, "-m", "forma_core.fluidics.benchmark",
                                 str(EXAMPLES / "broken-missing-outlet.json"), "--spec",
                                 str(EXAMPLES / "two-channel-spec.json")], cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(1, result.returncode, result.stderr)
        self.assertFalse(json.loads(result.stdout)["passed"])

    def test_project_validation_and_cli_reject_broken_network(self):
        project = HardwareIntermediateRepresentation.model_validate_json((EXAMPLES / "broken-missing-outlet.json").read_text())
        self.assertTrue(any(issue.category == "Fluidics: unknown_node" for issue in validate_project(project)))
        result = subprocess.run([sys.executable, "-m", "forma_core", "validate",
                                 str(EXAMPLES / "broken-missing-outlet.json")], cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(1, result.returncode, result.stderr)
        self.assertFalse(json.loads(result.stdout)["is_valid"])


if __name__ == "__main__":
    unittest.main()
