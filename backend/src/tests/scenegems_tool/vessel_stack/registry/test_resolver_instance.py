"""resolve_instance: whole-instance validation (shared layer, environment, speedup, attended runs)."""

import numpy as np
import pytest

from scenegems_tool.vessel_stack.contracts.adapter_spec import AdapterSpec, SpecStatus
from scenegems_tool.vessel_stack.contracts.capabilities import RepeatabilityTier
from scenegems_tool.vessel_stack.contracts.roles import AsvSystemId, ControlLayerId, LayerRef, SimulationLayerId
from scenegems_tool.vessel_stack.contracts.vessel_stack_config import AgentContext, EnvironmentConfig, SimulationInstanceConfig, VesselConfig, VesselStackConfig, WaveConfig
from scenegems_tool.vessel_stack.registry.catalog import build_registry, default_resolver
from scenegems_tool.vessel_stack.registry.resolver import StackResolver, StackUnavailableError
from tests.scenegems_tool.vessel_stack.scenarios import stack_instance, wind_environment

KINEMATIC = SimulationLayerId.KINEMATIC
GAZEBO = SimulationLayerId.GAZEBO
ARDUPILOT_SIM = SimulationLayerId.ARDUPILOT_SIM
NONE = ControlLayerId.NONE
ARDUPILOT = ControlLayerId.ARDUPILOT
CUSTOM = ControlLayerId.CUSTOM
REAL_VESSEL_STACK = VesselStackConfig(AsvSystemId.ON_BOARD, ControlLayerId.REAL_VESSEL, SimulationLayerId.REAL_VESSEL)


def with_real_vessel(instance: SimulationInstanceConfig) -> SimulationInstanceConfig:
    """The instance with a real vessel 9 that its own software steers."""
    instance.vessels["9"] = VesselConfig(agent_id="9", stack=REAL_VESSEL_STACK, context=AgentContext.REAL)
    return instance


def waves_environment() -> EnvironmentConfig:
    environment = EnvironmentConfig.calm()
    environment.wave = WaveConfig(amplitude=0.5, period=5.0, steepness=0.1, direction=np.array([1.0, 0.0]))
    return environment


@pytest.fixture
def resolver() -> StackResolver:
    return default_resolver()


class TestInstanceShape:
    def test_calm_available_instance_is_accepted(self, resolver):
        resolution = resolver.resolve_instance(stack_instance(KINEMATIC, [0, 1], control_layer=NONE))
        assert resolution.accepted
        assert resolution.errors == ()
        assert resolution.warnings == ()
        assert set(resolution.chains) == {"0", "1"}

    def test_unavailable_stack_is_rejected_with_the_vessel_and_the_reason(self, resolver):
        resolution = resolver.resolve_instance(stack_instance(GAZEBO, [0], control_layer=NONE))
        assert not resolution.accepted
        assert resolution.capabilities is None
        assert "vessel 0 (replay, none, gazebo)" in resolution.reason
        assert "Gazebo needs actuator commands" in resolution.reason

    def test_planned_stack_is_rejected_as_not_implemented(self):
        """No catalog spec is planned since Phase 2, so a planned alternative is registered as the default here."""
        registry = build_registry({})
        registry.register_adapter(
            AdapterSpec(
                id="planned_probe",
                source=LayerRef.of(AsvSystemId.USV_NAVIGATION),
                target=LayerRef.of(ControlLayerId.ARDUPILOT),
                description="A planned adapter for this test.",
                status=SpecStatus.PLANNED,
                planned_phase=3,
            ),
            default=True,
        )
        resolution = StackResolver(registry).resolve_instance(stack_instance(GAZEBO, [0], asv_system=AsvSystemId.USV_NAVIGATION))
        assert not resolution.accepted
        assert "planned_probe is planned for phase 3 and not implemented yet" in resolution.reason

    def test_vessels_must_share_the_instance_simulation_layer(self, resolver):
        instance = stack_instance(ARDUPILOT_SIM, [0])
        other = stack_instance(GAZEBO, [1]).vessels["1"]
        instance.vessels["1"] = other
        resolution = resolver.resolve_instance(instance)
        assert not resolution.accepted
        assert "vessel 1 uses simulation layer gazebo, but all vessels of one instance share ardupilot_sim" in resolution.reason

    def test_instance_without_vessels_has_no_capabilities(self, resolver):
        instance = SimulationInstanceConfig(simulation_layer=GAZEBO, environment=EnvironmentConfig.calm(), vessels={})
        resolution = resolver.resolve_instance(instance)
        assert resolution.accepted
        assert resolution.chains == {}
        assert resolution.capabilities is None
        assert resolution.repeatability_tier is None

    def test_real_vessels_are_resolved_on_their_own_layers(self, resolver):
        instance = with_real_vessel(stack_instance(GAZEBO, [0], adapter_ids=["replay_arduagent_follower"]))
        resolution = resolver.resolve_instance(instance)
        assert resolution.accepted
        assert set(resolution.chains) == {"0", "9"}
        assert resolution.chains["9"].asv_adapter.id == "on_board_arduagent_real_vessel"

    def test_a_real_vessel_makes_the_instance_workbench_only_and_real_time(self, resolver):
        instance = with_real_vessel(stack_instance(GAZEBO, [0], adapter_ids=["replay_arduagent_follower"]))
        capabilities = resolver.resolve_instance(instance).capabilities
        assert capabilities.interactive_only
        assert not capabilities.faster_than_real_time
        instance.speedup = 2
        assert "cannot run faster than real time" in resolver.resolve_instance(instance).reason

    def test_a_real_vessel_is_rejected_for_unattended_runs(self, resolver):
        resolution = resolver.resolve_instance(with_real_vessel(stack_instance(GAZEBO, [0])), attended=False)
        assert "is interactive only and is rejected for unattended runs: a physical vessel is run from the workbench only" in resolution.reason

    def test_requested_wind_applies_to_the_simulated_vessels_only(self, resolver):
        instance = with_real_vessel(stack_instance(GAZEBO, [0], environment=wind_environment(), adapter_ids=["replay_arduagent_follower"]))
        resolution = resolver.resolve_instance(instance)
        assert "real_vessel" not in resolution.reason
        assert all("real_vessel" not in warning for warning in resolution.warnings)

    def test_a_real_vessel_on_simulator_layers_is_rejected(self, resolver):
        instance = stack_instance(GAZEBO, [0])
        stack = VesselStackConfig(AsvSystemId.MISSION_PLANNER, ControlLayerId.CUSTOM, KINEMATIC)
        instance.vessels["9"] = VesselConfig(agent_id="9", stack=stack, context=AgentContext.REAL)
        resolution = resolver.resolve_instance(instance)
        assert not resolution.accepted
        assert "vessel 9 is a real vessel, so its control and simulation layers are real_vessel, not (mission_planner, custom, kinematic)" in resolution.reason

    def test_a_simulated_vessel_cannot_use_the_real_vessel_layers(self, resolver):
        instance = stack_instance(GAZEBO, [0])
        instance.vessels["1"] = VesselConfig(agent_id="1", stack=REAL_VESSEL_STACK)
        assert "vessel 1 uses simulation layer real_vessel, but all vessels of one instance share gazebo" in resolver.resolve_instance(instance).reason

    def test_an_instance_does_not_run_on_the_real_vessel_layer(self, resolver):
        instance = SimulationInstanceConfig(simulation_layer=SimulationLayerId.REAL_VESSEL, environment=EnvironmentConfig.calm())
        assert "real_vessel is the layer of a real vessel only" in resolver.resolve_instance(instance).reason

    def test_require_raises_with_every_reason(self, resolver):
        resolution = resolver.resolve_instance(stack_instance(GAZEBO, [0], control_layer=NONE))
        with pytest.raises(StackUnavailableError) as error:
            resolution.require()
        assert error.value.reasons == resolution.errors
        assert "Gazebo needs actuator commands" in str(error.value)

    def test_require_returns_an_accepted_resolution(self, resolver):
        resolution = resolver.require_instance(stack_instance(ARDUPILOT_SIM, [0]))
        assert resolution.accepted

    def test_capabilities_are_the_weakest_link_over_all_vessels(self, resolver):
        instance = stack_instance(ARDUPILOT_SIM, [0])
        instance.vessels["1"] = VesselConfig(agent_id="1", stack=VesselStackConfig(AsvSystemId.MISSION_PLANNER, ARDUPILOT, ARDUPILOT_SIM))
        resolution = resolver.resolve_instance(instance)
        assert resolution.accepted
        assert resolution.capabilities.interactive_only
        assert resolution.capabilities.repeatability_tier == RepeatabilityTier.NONE

    def test_workbench_adapter_selection_keeps_exact_repeatability_at_one_x(self, resolver):
        instance = stack_instance(ARDUPILOT_SIM, [0], adapter_ids=["replay_arduagent_follower"])
        resolution = resolver.resolve_instance(instance)
        assert resolution.repeatability_tier == RepeatabilityTier.EXACT
        instance.speedup = 5
        assert resolver.resolve_instance(instance).repeatability_tier == RepeatabilityTier.BOUNDED


class TestAttended:
    def test_mission_planner_is_accepted_attended(self, resolver):
        instance = stack_instance(GAZEBO, [0], asv_system=AsvSystemId.MISSION_PLANNER)
        assert resolver.resolve_instance(instance, attended=True).accepted

    def test_mission_planner_is_rejected_unattended_with_the_note(self, resolver):
        instance = stack_instance(GAZEBO, [0], asv_system=AsvSystemId.MISSION_PLANNER)
        resolution = resolver.resolve_instance(instance, attended=False)
        assert not resolution.accepted
        assert "asv_system/mission_planner is interactive only and is rejected for unattended runs: a person drives the vessel" in resolution.reason

    def test_replay_is_accepted_unattended(self, resolver):
        assert resolver.resolve_instance(stack_instance(ARDUPILOT_SIM, [0]), attended=False).accepted


class TestEnvironment:
    def test_wind_is_rejected_on_the_kinematic_layer(self, resolver):
        resolution = resolver.resolve_instance(stack_instance(KINEMATIC, [0], control_layer=NONE, environment=wind_environment()))
        assert not resolution.accepted
        assert "wind requested, but simulation_layer/kinematic does not support wind: the kinematic model has no wind or wave forces" in resolution.reason

    def test_waves_are_rejected_on_the_kinematic_layer(self, resolver):
        resolution = resolver.resolve_instance(stack_instance(KINEMATIC, [0], control_layer=NONE, environment=waves_environment()))
        assert not resolution.accepted
        assert "waves requested, but simulation_layer/kinematic does not support waves" in resolution.reason

    def test_wind_is_rejected_on_ardupilot_sim_with_the_measured_reason(self, resolver):
        resolution = resolver.resolve_instance(stack_instance(ARDUPILOT_SIM, [0], environment=wind_environment()))
        assert not resolution.accepted
        assert "wind requested, but simulation_layer/ardupilot_sim does not support wind: 5 m/s cross wind had no measurable effect" in resolution.reason

    def test_waves_are_accepted_on_ardupilot_sim_without_a_warning(self, resolver):
        resolution = resolver.resolve_instance(stack_instance(ARDUPILOT_SIM, [0], environment=waves_environment()))
        assert resolution.accepted
        assert resolution.warnings == ()

    def test_wind_is_accepted_on_gazebo(self, resolver):
        resolution = resolver.resolve_instance(stack_instance(GAZEBO, [0], environment=wind_environment()))
        assert resolution.accepted

    def test_waves_are_accepted_on_gazebo_without_a_warning_now_that_asv_wave_sim_is_measured(self, resolver):
        for control in (ARDUPILOT, CUSTOM):
            resolution = resolver.resolve_instance(stack_instance(GAZEBO, [0], control_layer=control, environment=waves_environment()))
            assert resolution.accepted
            assert resolution.warnings == ()

    def test_wind_and_waves_together_give_both_errors(self, resolver):
        environment = waves_environment()
        environment.wind_vector = np.array([0.0, 5.0, 0.0])
        resolution = resolver.resolve_instance(stack_instance(KINEMATIC, [0], control_layer=NONE, environment=environment))
        assert len(resolution.errors) == 2

    def test_calm_environment_is_accepted_everywhere(self, resolver):
        for simulation, control in ((KINEMATIC, NONE), (GAZEBO, ARDUPILOT), (ARDUPILOT_SIM, ARDUPILOT)):
            assert resolver.resolve_instance(stack_instance(simulation, [0], control_layer=control)).accepted

    def test_unmeasured_support_warns_and_accepts(self):
        resolver = StackResolver(build_registry({}))
        resolution = resolver.resolve_instance(stack_instance(ARDUPILOT_SIM, [0], environment=waves_environment()))
        assert resolution.accepted
        assert any("support for waves in simulation_layer/ardupilot_sim is unmeasured" in warning for warning in resolution.warnings)

    def test_effective_environment_of_a_calm_request_is_empty(self, resolver):
        resolution = resolver.resolve_instance(stack_instance(KINEMATIC, [0], control_layer=NONE))
        assert resolution.effective_environment() == {"wind_vector": None, "waves": None, "seed": 0}

    def test_effective_environment_records_what_is_applied(self, resolver):
        environment = waves_environment()
        environment.wind_vector = np.array([1.0, 2.0, 0.0])
        environment.seed = 42
        resolution = resolver.resolve_instance(stack_instance(ARDUPILOT_SIM, [0], environment=environment))
        effective = resolution.effective_environment()
        assert effective["wind_vector"] == [1.0, 2.0, 0.0]
        assert effective["waves"] == {"amplitude": 0.5, "period": 5.0, "steepness": 0.1, "direction": [1.0, 0.0]}
        assert effective["seed"] == 42


class TestSpeedup:
    def test_below_one_is_rejected(self, resolver):
        resolution = resolver.resolve_instance(stack_instance(KINEMATIC, [0], control_layer=NONE, speedup=0))
        assert not resolution.accepted
        assert "speedup 0 is below 1; slower than real time is not supported" in resolution.reason

    def test_real_time_is_always_accepted(self, resolver):
        assert resolver.resolve_instance(stack_instance(GAZEBO, [0], speedup=1)).accepted

    def test_kinematic_has_no_speed_limit(self, resolver):
        resolution = resolver.resolve_instance(stack_instance(KINEMATIC, [0], control_layer=NONE, speedup=100000))
        assert resolution.accepted
        assert resolution.warnings == ()

    def test_ardupilot_sim_accepts_up_to_the_measured_limit_of_the_lockstep_link(self, resolver):
        assert resolver.resolve_instance(stack_instance(ARDUPILOT_SIM, [0], speedup=50)).accepted

    def test_ardupilot_sim_rejects_above_the_measured_limit(self, resolver):
        resolution = resolver.resolve_instance(stack_instance(ARDUPILOT_SIM, [0], speedup=51))
        assert not resolution.accepted
        assert "speedup 51 exceeds the measured max_speedup 50 of replay_mavlink_lockstep" in resolution.reason

    def test_arduagent_path_on_ardupilot_sim_goes_up_to_100(self, resolver):
        instance = stack_instance(ARDUPILOT_SIM, [0], adapter_ids=["replay_arduagent_follower"], speedup=100)
        assert resolver.resolve_instance(instance).accepted
        instance.speedup = 101
        resolution = resolver.resolve_instance(instance)
        assert not resolution.accepted
        assert "exceeds the measured max_speedup 100 of sitl_internal_physics" in resolution.reason

    def test_gazebo_without_a_host_warns_about_the_per_host_value(self, resolver):
        resolution = resolver.resolve_instance(stack_instance(GAZEBO, [0], speedup=10))
        assert resolution.accepted
        assert any("speedup 10 is unverified" in warning and "4.4x on phase0_windows_12_core" in warning for warning in resolution.warnings)

    def test_gazebo_with_a_measured_host_enforces_its_limit(self, resolver):
        resolution = resolver.resolve_instance(stack_instance(GAZEBO, [0], speedup=5), host="phase0_windows_12_core")
        assert not resolution.accepted
        assert "speedup 5 exceeds the measured max_speedup 4.4 of ardupilot_gazebo_plugin on phase0_windows_12_core" in resolution.reason

    def test_gazebo_with_a_measured_host_accepts_below_its_limit(self, resolver):
        resolution = resolver.resolve_instance(stack_instance(GAZEBO, [0], speedup=4), host="phase0_windows_12_core")
        assert resolution.accepted
        assert resolution.warnings == ()

    def test_gazebo_with_an_unknown_host_warns(self, resolver):
        resolution = resolver.resolve_instance(stack_instance(GAZEBO, [0], speedup=3), host="some_other_machine")
        assert resolution.accepted
        assert resolution.warnings

    def test_wall_clock_chain_is_capped_at_one_x(self):
        from dataclasses import replace

        registry = build_registry()
        capped = registry.adapter("replay_mavlink_lockstep")
        registry._adapters_by_id["replay_mavlink_lockstep"] = replace(capped, capabilities=replace(capped.capabilities, faster_than_real_time=False))
        registry._adapters[(capped.source, capped.target)] = registry._adapters_by_id["replay_mavlink_lockstep"]
        resolution = StackResolver(registry).resolve_instance(stack_instance(ARDUPILOT_SIM, [0], speedup=2))
        assert not resolution.accepted
        assert "cannot run faster than real time, so this stack is capped at 1x" in resolution.reason

    def test_unmeasured_limit_warns(self):
        resolver = StackResolver(build_registry({}))
        resolution = resolver.resolve_instance(stack_instance(ARDUPILOT_SIM, [0], speedup=5))
        assert resolution.accepted
        assert any("speedup 5 is unverified" in warning for warning in resolution.warnings)
