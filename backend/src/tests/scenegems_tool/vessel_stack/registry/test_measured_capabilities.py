"""The measured capability loader: parsing, applying to specs, and failing on unknown ids and fields."""

import math

import pytest
import yaml

from logical_level.mapping.vessel_type import SteeringType
from scenegems_tool.vessel_stack.contracts.capabilities import Capabilities, EnvironmentSupport, RepeatabilityTier
from scenegems_tool.vessel_stack.registry.catalog import build_registry, default_registry
from scenegems_tool.vessel_stack.registry.measured_capabilities import (
    MEASURED_CAPABILITIES_FILE,
    CapabilityMeasurement,
    load_capability_measurements,
    parse_capability_measurement,
)


def write_measurements(tmp_path, text: str) -> str:
    path = tmp_path / "measured.yaml"
    path.write_text(text, encoding="utf-8")
    return str(path)


class TestParse:
    def test_capability_fields_are_typed(self):
        measurement = parse_capability_measurement(
            "some_spec",
            {"repeatability_tier": "bounded", "exact_up_to_speedup": 1, "max_speedup": 50, "wind": "supported", "waves": "unmeasured", "lockstep": False, "faster_than_real_time": True},
        )
        overrides = dict(measurement.overrides)
        assert overrides["repeatability_tier"] == RepeatabilityTier.BOUNDED
        assert overrides["exact_up_to_speedup"] == 1.0
        assert overrides["max_speedup"] == 50.0
        assert overrides["wind"] == EnvironmentSupport.SUPPORTED
        assert overrides["waves"] == EnvironmentSupport.UNMEASURED
        assert overrides["lockstep"] is False
        assert overrides["faster_than_real_time"] is True

    def test_steering_types_are_a_list_of_names(self):
        measurement = parse_capability_measurement("some_spec", {"steering_types": ["skid", "rudder"]})
        assert dict(measurement.overrides)["steering_types"] == frozenset({SteeringType.RUDDER, SteeringType.SKID})
        assert measurement.apply(Capabilities()).steering_types == {SteeringType.RUDDER, SteeringType.SKID}

    def test_one_steering_type_may_be_given_as_a_name(self):
        assert dict(parse_capability_measurement("some_spec", {"steering_types": "vectored_thrust"}).overrides)["steering_types"] == frozenset({SteeringType.VECTORED_THRUST})

    @pytest.mark.parametrize("value", [["rudder", "sail"], "paddle", [], None])
    def test_an_unknown_or_missing_steering_type_fails(self, value):
        with pytest.raises(ValueError):
            parse_capability_measurement("some_spec", {"steering_types": value})

    def test_null_max_speedup_means_not_measured(self):
        measurement = parse_capability_measurement("some_spec", {"max_speedup": None})
        assert dict(measurement.overrides)["max_speedup"] is None

    def test_infinite_max_speedup(self):
        measurement = parse_capability_measurement("some_spec", {"max_speedup": float("inf")})
        assert math.isinf(dict(measurement.overrides)["max_speedup"])

    def test_record_fields_are_not_capabilities(self):
        measurement = parse_capability_measurement(
            "some_spec",
            {
                "notes": {"waves": "no wave system"},
                "deviation_bounds_m": {5: 0.083, 1: 0.0},
                "deviation_bounds_m_by_layer": {"simulation_layer/gazebo": {2: 0.054, 1: 0.184}},
                "host_max_speedup": {"host_b": 3, "host_a": 4.4},
                "evidence": "  measured on a bench  ",
            },
        )
        assert measurement.overrides == ()
        assert measurement.notes == (("waves", "no wave system"),)
        assert measurement.deviation_bounds_m == ((1.0, 0.0), (5.0, 0.083))
        assert measurement.deviation_bounds_m_by_layer == (("simulation_layer/gazebo", ((1.0, 0.184), (2.0, 0.054))),)
        assert measurement.host_max_speedup == (("host_a", 4.4), ("host_b", 3.0))
        assert measurement.evidence == "measured on a bench"

    def test_unknown_field_fails_and_names_the_spec_and_field(self):
        with pytest.raises(ValueError, match=r"some_spec: unknown measured capability fields \['max_spedup'\]"):
            parse_capability_measurement("some_spec", {"max_spedup": 5})

    def test_several_unknown_fields_are_all_named(self):
        with pytest.raises(ValueError, match=r"\['alpha', 'beta'\]"):
            parse_capability_measurement("some_spec", {"beta": 1, "alpha": 2, "wind": "supported"})

    @pytest.mark.parametrize("field,value", [("repeatability_tier", "approximately"), ("wind", "maybe"), ("waves", "yes")])
    def test_invalid_enum_value_fails(self, field, value):
        with pytest.raises(ValueError):
            parse_capability_measurement("some_spec", {field: value})

    def test_non_numeric_speedup_fails(self):
        with pytest.raises(ValueError):
            parse_capability_measurement("some_spec", {"max_speedup": "fast"})

    def test_host_lookup(self):
        measurement = parse_capability_measurement("some_spec", {"host_max_speedup": {"host_a": 4.4}})
        assert measurement.max_speedup_on("host_a") == 4.4
        assert measurement.max_speedup_on("host_b") is None
        assert measurement.max_speedup_on(None) is None

    def test_apply_replaces_only_the_measured_fields(self):
        measurement = parse_capability_measurement("some_spec", {"repeatability_tier": "bounded", "max_speedup": 20})
        base = Capabilities(wind=EnvironmentSupport.UNSUPPORTED)
        applied = measurement.apply(base)
        assert applied.repeatability_tier == RepeatabilityTier.BOUNDED
        assert applied.max_speedup == 20.0
        assert applied.wind == EnvironmentSupport.UNSUPPORTED


class TestLoad:
    def test_loads_a_file(self, tmp_path):
        path = write_measurements(tmp_path, "spec_a:\n  max_speedup: 7\nspec_b:\n  wind: supported\n")
        measurements = load_capability_measurements(path)
        assert set(measurements) == {"spec_a", "spec_b"}
        assert dict(measurements["spec_a"].overrides) == {"max_speedup": 7.0}

    def test_empty_file_loads_nothing(self, tmp_path):
        assert load_capability_measurements(write_measurements(tmp_path, "")) == {}

    def test_empty_entry_is_allowed(self, tmp_path):
        measurements = load_capability_measurements(write_measurements(tmp_path, "spec_a:\n"))
        assert measurements["spec_a"].overrides == ()

    def test_unknown_field_in_the_file_fails_the_load(self, tmp_path):
        with pytest.raises(ValueError, match="unknown measured capability fields"):
            load_capability_measurements(write_measurements(tmp_path, "spec_a:\n  max_speed: 7\n"))

    def test_the_shipped_file_loads(self):
        measurements = load_capability_measurements()
        assert measurements
        assert all(isinstance(measurement, CapabilityMeasurement) for measurement in measurements.values())

    def test_infinity_literal_in_yaml(self, tmp_path):
        measurements = load_capability_measurements(write_measurements(tmp_path, "spec_a:\n  max_speedup: .inf\n"))
        assert math.isinf(dict(measurements["spec_a"].overrides)["max_speedup"])


class TestRegistryBuild:
    def test_unknown_spec_id_fails_the_registry_build(self):
        measurements = {"no_such_adapter": parse_capability_measurement("no_such_adapter", {"max_speedup": 5})}
        with pytest.raises(ValueError, match="Measured capabilities for unregistered specs: no_such_adapter"):
            build_registry(measurements)

    def test_every_unknown_id_is_listed(self):
        measurements = {name: parse_capability_measurement(name, {}) for name in ("zeta", "alpha")}
        with pytest.raises(ValueError, match="alpha, zeta"):
            build_registry(measurements)

    def test_a_typo_in_a_shipped_id_is_caught(self, tmp_path):
        text = open(MEASURED_CAPABILITIES_FILE, encoding="utf-8").read().replace("sitl_internal_physics:", "sitl_internal_physic:", 1)
        path = tmp_path / "typo.yaml"
        path.write_text(text, encoding="utf-8")
        with pytest.raises(ValueError, match="sitl_internal_physic"):
            build_registry(load_capability_measurements(str(path)))

    def test_unknown_field_in_a_shipped_entry_is_caught(self, tmp_path):
        text = open(MEASURED_CAPABILITIES_FILE, encoding="utf-8").read().replace("  max_speedup: 100\n", "  max_speedupp: 100\n", 1)
        path = tmp_path / "typo.yaml"
        path.write_text(text, encoding="utf-8")
        with pytest.raises(ValueError, match="max_speedupp"):
            load_capability_measurements(str(path))

    def test_every_shipped_entry_matches_a_registered_spec(self):
        registry = default_registry()
        registered = {spec.id for spec in registry.layers} | {spec.id for spec in registry.adapters}
        assert set(load_capability_measurements()) <= registered

    def test_measured_values_reach_the_specs(self):
        registry = default_registry()
        sitl = registry.adapter("sitl_internal_physics")
        assert sitl.capabilities.repeatability_tier == RepeatabilityTier.BOUNDED
        assert sitl.capabilities.exact_up_to_speedup == 1
        assert sitl.capabilities.max_speedup == 100
        kinematic = registry.adapter("kinematic_command_input")
        assert kinematic.capabilities.repeatability_tier == RepeatabilityTier.EXACT
        assert math.isinf(kinematic.capabilities.max_speedup)

    def test_measurement_notes_become_restriction_notes(self):
        layer = default_registry().layer(next(spec.layer for spec in default_registry().layers if spec.id == "simulation_layer/ardupilot_sim"))
        assert layer.capabilities.wind == EnvironmentSupport.UNSUPPORTED
        assert "no measurable effect" in layer.note_for("wind")

    def test_ardupilot_sim_runs_rudder_and_skid_vessels_only_and_every_other_spec_all_three(self):
        """SITL's boat has a rudder or two motors; the spec declares it, so it holds without the measurement file too."""
        for registry in (default_registry(), build_registry({})):
            for spec in (*registry.layers, *registry.adapters):
                expected = {SteeringType.RUDDER, SteeringType.SKID} if spec.id == "simulation_layer/ardupilot_sim" else set(SteeringType)
                assert spec.capabilities.steering_types == expected, spec.id
            layer = next(spec for spec in registry.layers if spec.id == "simulation_layer/ardupilot_sim")
            assert "no thruster that turns" in layer.note_for("steering_types")

    def test_what_a_simulator_steers_by_is_declared_in_its_spec_and_not_repeated_as_a_measurement(self):
        assert all("steering_types" not in dict(measurement.overrides) for measurement in load_capability_measurements().values())

    def test_a_measured_entry_narrows_the_steering_types_of_its_spec(self):
        registry = build_registry(
            {"simulation_layer/gazebo": parse_capability_measurement("simulation_layer/gazebo", {"steering_types": ["skid"], "notes": {"steering_types": "only the twin hull was run"}})}
        )
        gazebo = next(spec for spec in registry.layers if spec.id == "simulation_layer/gazebo")
        assert gazebo.capabilities.steering_types == {SteeringType.SKID}
        assert gazebo.note_for("steering_types") == "only the twin hull was run"

    def test_without_measurements_specs_keep_their_declared_defaults(self):
        registry = build_registry({})
        sitl = registry.adapter("sitl_internal_physics")
        assert sitl.capabilities.max_speedup is None
        assert registry.layer(next(spec.layer for spec in registry.layers if spec.id == "simulation_layer/ardupilot_sim")).capabilities.waves == EnvironmentSupport.UNMEASURED

    def test_host_values_are_kept_for_the_gazebo_link(self):
        measurement = default_registry().measurement("ardupilot_gazebo_plugin")
        assert measurement.max_speedup_on("phase0_windows_12_core") == 4.4
        assert default_registry().adapter("ardupilot_gazebo_plugin").capabilities.max_speedup is None

    def test_shipped_yaml_is_plain_data(self):
        with open(MEASURED_CAPABILITIES_FILE, encoding="utf-8") as file:
            data = yaml.safe_load(file)
        assert all(isinstance(entry, dict) for entry in data.values())
