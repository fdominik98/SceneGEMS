"""Stack runs for the calibration: stack preparation and result handling without Docker, and one real run marked docker."""

import os

import numpy as np
import pytest
import yaml

from scenegems_tool.vessel_stack.calibration.measured_entry import host_label
from scenegems_tool.vessel_stack.calibration.reference_scenarios import straight_run
from scenegems_tool.vessel_stack.calibration.repeat_analysis import DeviationSummary, TrackSamples
from scenegems_tool.vessel_stack.calibration.sitl_stack_runs import (
    CONTAINER_ASSETS,
    HullMotion,
    RepeatResult,
    StackMeasurement,
    StackRunSpec,
    compose_project_name,
    host_assets_replacements,
    measure_stack,
    prepare_run_folder,
    uncapped_generation,
)
from scenegems_tool.vessel_stack.contracts.roles import AsvSystemId, ControlLayerId, SimulationLayerId
from scenegems_tool.vessel_stack.registry.catalog import default_resolver
from utils.file_system_utils import RUNTIME_ASSETS_FOLDER

ARDUPILOT_SIM = SimulationLayerId.ARDUPILOT_SIM
GAZEBO = SimulationLayerId.GAZEBO
CUSTOM = ControlLayerId.CUSTOM


def track() -> TrackSamples:
    time_s = np.arange(0.0, 30.0, 0.5)
    return TrackSamples(time_s, 3 * time_s, np.zeros_like(time_s), np.full_like(time_s, 3.0))


def deviation(max_m=0.07, alignment="scenario_time") -> DeviationSummary:
    return DeviationSummary(alignment, 2, max_m, max_m / 2, 25.0, None, False)


def measurement(layer=ARDUPILOT_SIM, drive="replay", speedup=5, achieved=5.0, dev=0.07, repeats=2) -> StackMeasurement:
    spec = StackRunSpec(layer, "straight", "5m", 30, speedup, repeats, drive)
    results = [RepeatResult(index=index, track=track(), achieved_speedup=achieved) for index in range(repeats)]
    return StackMeasurement(spec, results, deviation(dev, "scenario_time" if drive == "replay" else "onset"))


class TestStackPreparation:
    @pytest.fixture(scope="module")
    def prepared(self, tmp_path_factory):
        folder = str(tmp_path_factory.mktemp("run"))
        spec = StackRunSpec(GAZEBO, "straight", "5m", 20, 2, 1)
        with uncapped_generation():
            compose_file, endpoints, instance = prepare_run_folder(spec, straight_run("5m", 20), folder, 16000)
        return folder, compose_file, endpoints, instance

    def test_generated_files_land_under_the_mounted_assets_folder(self, prepared):
        folder, _, _, _ = prepared
        generated = os.path.join(folder, "runtime_assets", "scenario_execution", "gen_tmp")
        assert {"ocean_world.sdf", "vessel_0_model.sdf", "params-vessel_0.params", "trajectories.json"} <= set(os.listdir(generated))

    def test_no_host_path_is_left_in_the_files(self, prepared):
        folder, compose_file, _, _ = prepared
        texts = [open(compose_file, encoding="utf-8").read()]
        generated = os.path.join(folder, "runtime_assets", "scenario_execution", "gen_tmp")
        texts += [open(os.path.join(generated, name), encoding="utf-8").read() for name in os.listdir(generated) if name != "trajectories.json"]
        for text in texts:
            assert RUNTIME_ASSETS_FOLDER not in text and RUNTIME_ASSETS_FOLDER.replace("\\", "/") not in text
        assert f"{CONTAINER_ASSETS}/scenario_execution/gen_tmp/vessel_0_model.sdf" in open(os.path.join(generated, "ocean_world.sdf"), encoding="utf-8").read()

    def test_the_shared_volume_becomes_a_bind_mount_of_the_run_folder(self, prepared):
        folder, compose_file, _, _ = prepared
        compose = yaml.safe_load(open(compose_file, encoding="utf-8"))
        assert "volumes" not in compose
        for service in compose["services"].values():
            (volume,) = service["volumes"]
            assert volume.endswith(f"runtime_assets:{CONTAINER_ASSETS}:ro")
            assert os.path.abspath(folder).replace("\\", "/") in volume

    def test_each_sitl_serial_port_is_published_on_a_host_port(self, prepared):
        _, compose_file, endpoints, _ = prepared
        compose = yaml.safe_load(open(compose_file, encoding="utf-8"))
        assert compose["services"]["vessel_0"]["ports"] == ["127.0.0.1:16000:5760"]
        assert endpoints == {"0": "tcp:127.0.0.1:16000"}

    def test_fixed_names_and_the_gazebo_host_port_are_dropped_so_repeats_can_coexist(self, prepared):
        _, compose_file, _, _ = prepared
        compose = yaml.safe_load(open(compose_file, encoding="utf-8"))
        assert all("container_name" not in service for service in compose["services"].values())
        assert "ports" not in compose["services"]["gazebo"]
        assert compose["networks"] == {"maritime_net": {"driver": "bridge"}}

    def test_the_instance_replays_through_the_lockstep_adapter(self, prepared):
        _, _, _, instance = prepared
        assert instance.speedup == 2
        assert instance.vessels["0"].adapter_ids == ("replay_mavlink_lockstep",)

    def test_wind_reaches_the_world_and_the_parameters(self, tmp_path):
        spec = StackRunSpec(GAZEBO, "straight", "5m", 20, 1, 1, wind=(0.0, 5.0))
        with uncapped_generation():
            prepare_run_folder(spec, straight_run("5m", 20), str(tmp_path), 16100)
        generated = tmp_path / "runtime_assets" / "scenario_execution" / "gen_tmp"
        assert "<linear_velocity>0.0 5.0 0.0</linear_velocity>" in (generated / "ocean_world.sdf").read_text(encoding="utf-8")
        assert "SIM_WIND_SPD\t5.0" in (generated / "params-vessel_0.params").read_text(encoding="utf-8")

    def test_repo_entrypoints_are_mounted_over_the_image_copies_on_request(self, tmp_path):
        spec = StackRunSpec(GAZEBO, "straight", "5m", 20, 1, 1)
        with uncapped_generation():
            compose_file, _, _ = prepare_run_folder(spec, straight_run("5m", 20), str(tmp_path), 16200, repo_entrypoints=True)
        services = yaml.safe_load(open(compose_file, encoding="utf-8"))["services"]
        assert any(volume.endswith("sitl_entrypoint.sh:/scripts/sitl_entrypoint.sh:ro") for volume in services["vessel_0"]["volumes"])
        assert any("gazebo_entrypoint_prod.sh" in volume for volume in services["gazebo"]["volumes"])

    def test_replacements_cover_the_spellings_of_the_assets_folder(self):
        assert all(new == CONTAINER_ASSETS for _, new in host_assets_replacements())
        assert RUNTIME_ASSETS_FOLDER in [old for old, _ in host_assets_replacements()]


class TestUncappedGeneration:
    def test_a_speedup_beyond_the_stored_limit_can_be_generated_while_the_block_lasts(self, tmp_path):
        spec = StackRunSpec(ARDUPILOT_SIM, "straight", "5m", 20, 500, 1)
        with uncapped_generation():
            prepare_run_folder(spec, straight_run("5m", 20), str(tmp_path), 16300)
        from scenegems_tool.vessel_stack.registry.resolver import StackUnavailableError

        with pytest.raises(StackUnavailableError, match="exceeds the measured max_speedup"):
            from scenegems_tool.vessel_stack.simulation_docker_stack import build_simulation_docker_stack_artifacts  # noqa: F401
            from tests.scenegems_tool.vessel_stack.scenarios import GEOFENCE, mqtt_connection, stack_instance

            build_simulation_docker_stack_artifacts(stack_instance(ARDUPILOT_SIM, [0], speedup=500), straight_run("5m", 20), mqtt_connection(), GEOFENCE)

    def test_the_default_resolver_is_restored(self):
        before = default_resolver().registry
        with uncapped_generation():
            pass
        assert default_resolver().registry is before


class TestMeasurementEntries:
    def test_a_tracked_ardupilot_sim_replay_run_gives_the_adapter_entry(self):
        (entry,) = measurement().entries()
        assert entry.spec_id == "replay_mavlink_lockstep"
        assert entry.fields["deviation_bounds_m_by_layer"] == {"simulation_layer/ardupilot_sim": {5: 0.07}}
        assert entry.fields["max_speedup"] == 5.0
        entry.parsed()

    def test_a_run_that_did_not_track_its_request_claims_no_speed_limit(self):
        (entry,) = measurement(achieved=2.0).entries()
        assert "max_speedup" not in entry.fields
        assert "deviation_bounds_m_by_layer" in entry.fields

    def test_a_tracked_gazebo_replay_run_also_gives_the_host_limit_of_the_plugin(self):
        entries = measurement(layer=GAZEBO, speedup=2, achieved=1.95).entries()
        assert [entry.spec_id for entry in entries] == ["replay_mavlink_lockstep", "ardupilot_gazebo_plugin"]
        assert entries[0].fields["deviation_bounds_m_by_layer"] == {"simulation_layer/gazebo": {2: 0.07}}
        assert "max_speedup" not in entries[0].fields, "the Gazebo pace is a per-host value"
        assert entries[1].fields["host_max_speedup"] == {host_label(): 2.0}

    def test_a_target_drive_gives_the_entry_of_the_control_and_simulation_pair(self):
        (entry,) = measurement(drive="target", speedup=5, achieved=5.0).entries()
        assert entry.spec_id == "sitl_internal_physics"
        assert entry.fields["deviation_bounds_m"] == {5: 0.07}
        assert entry.fields["max_speedup"] == 5.0
        (gazebo_entry,) = measurement(layer=GAZEBO, drive="target", speedup=2, achieved=2.0).entries()
        assert gazebo_entry.spec_id == "ardupilot_gazebo_plugin"
        assert gazebo_entry.fields["host_max_speedup"] == {host_label(): 2.0}

    def test_a_usv_navigation_drive_gives_the_entry_of_its_lockstep_adapter(self):
        (entry,) = measurement(drive="usv_navigation").entries()
        assert entry.spec_id == "usv_navigation_mavlink_lockstep"
        assert entry.fields["deviation_bounds_m_by_layer"] == {"simulation_layer/ardupilot_sim": {5: 0.07}}
        assert entry.fields["max_speedup"] == 5.0
        entry.parsed()

    def test_a_usv_navigation_drive_runs_usv_navigation_on_every_sitl(self, tmp_path):
        spec = StackRunSpec(ARDUPILOT_SIM, "straight", "5m", 20, 1, 1, "usv_navigation")
        with uncapped_generation():
            _, endpoints, instance = prepare_run_folder(spec, straight_run("5m", 20), str(tmp_path), 16420)
        assert instance.vessels["0"].stack.asv_system == AsvSystemId.USV_NAVIGATION
        assert instance.vessels["0"].adapter_ids == ("usv_navigation_mavlink_lockstep",)
        assert endpoints == {"0": "tcp:127.0.0.1:16420"}

    def test_the_evidence_names_the_method_and_the_numbers(self):
        (entry,) = measurement().entries()
        evidence = entry.fields["evidence"]
        for part in ("replay drive", "straight 5m run", "requested 5x", "achieved 5.00x", "max deviation m 0.070"):
            assert part in evidence

    def test_without_a_second_repeat_there_is_no_deviation_bound(self):
        single = measurement(repeats=1)
        single.deviation = None
        (entry,) = single.entries()
        assert "deviation_bounds_m_by_layer" not in entry.fields

    def test_failed_repeats_give_no_entries(self):
        failed = StackMeasurement(StackRunSpec(ARDUPILOT_SIM), [RepeatResult(index=0, error="no heartbeat"), RepeatResult(index=1, error="no heartbeat")])
        assert failed.entries() == []
        assert failed.achieved is None and not failed.tracks_request

    def test_a_failed_repeat_is_left_out_of_the_pace(self):
        mixed = measurement()
        mixed.repeats.append(RepeatResult(index=2, error="timeout"))
        assert len(mixed.ok_repeats) == 2
        assert mixed.achieved == 5.0

    def test_the_slowest_repeat_decides_whether_the_request_was_tracked(self):
        run = measurement()
        run.repeats[1].achieved_speedup = 4.0
        assert run.achieved == 4.0
        assert not run.tracks_request, "4x of 5x is below 90 percent"

    def test_labels_name_layer_drive_reference_scale_and_speedup(self):
        assert StackRunSpec(GAZEBO, "turning", "30m", 90, 4, 3, "target").label() == "gazebo-target-turning-30m-4x"


class TestCustomController:
    def custom(self, drive="replay", digests=("a", "a"), late=(0, 0), achieved=7.5, dev=0.0):
        spec = StackRunSpec(GAZEBO, "straight", "5m", 30, 1, 2, drive, control_layer=CUSTOM)
        results = [RepeatResult(index=index, track=track(), achieved_speedup=achieved, state_digest=digest, late_commands=count) for index, (digest, count) in enumerate(zip(digests, late))]
        return StackMeasurement(spec, results, deviation(dev))

    def test_the_stack_is_gazebo_alone_with_the_actuator_port_published(self, tmp_path):
        spec = StackRunSpec(GAZEBO, "straight", "5m", 20, 1, 1, control_layer=CUSTOM)
        with uncapped_generation():
            compose_file, endpoints, instance = prepare_run_folder(spec, straight_run("5m", 20), str(tmp_path), 16400)
        services = yaml.safe_load(open(compose_file, encoding="utf-8"))["services"]
        assert list(services) == ["gazebo"]
        assert services["gazebo"]["ports"] == ["127.0.0.1:16400:11400"]
        assert endpoints == {"actuator": "127.0.0.1:16400"}
        assert instance.vessels["0"].stack.asv_system == AsvSystemId.REPLAY

    def test_the_usv_navigation_drive_puts_usv_navigation_on_every_vessel(self, tmp_path):
        spec = StackRunSpec(GAZEBO, "straight", "5m", 20, 1, 1, "usv_navigation", control_layer=CUSTOM)
        with uncapped_generation():
            _, _, instance = prepare_run_folder(spec, straight_run("5m", 20), str(tmp_path), 16410)
        assert instance.vessels["0"].stack.asv_system == AsvSystemId.USV_NAVIGATION
        assert spec.label() == "gazebo-custom-usv_navigation-straight-5m-1x"

    def test_identical_digests_without_late_thrust_are_the_exact_tier(self):
        (entry,) = self.custom().entries()
        assert entry.spec_id == "gz_transport_actuator"
        assert entry.fields["repeatability_tier"] == "exact"
        assert "deviation_bounds_m" not in entry.fields
        assert entry.fields["host_max_speedup"] == {host_label(): 7.5}
        entry.parsed()

    def test_a_late_thrust_makes_the_tier_bounded_by_the_measured_deviation(self):
        (entry,) = self.custom(late=(1, 0), dev=0.003).entries()
        assert entry.fields["repeatability_tier"] == "bounded"
        assert entry.fields["deviation_bounds_m"] == {1: 0.003}
        assert "late commands 1" in entry.fields["evidence"]

    def test_differing_digests_make_the_tier_bounded(self):
        (entry,) = self.custom(digests=("a", "b"), dev=0.01).entries()
        assert entry.fields["repeatability_tier"] == "bounded"

    def test_waves_reach_the_world_and_the_hull(self, tmp_path):
        spec = StackRunSpec(GAZEBO, "straight", "5m", 20, 1, 1, control_layer=CUSTOM, waves=(0.5, 5.0))
        with uncapped_generation():
            _, _, instance = prepare_run_folder(spec, straight_run("5m", 20), str(tmp_path), 16430)
        assert instance.environment.wave.amplitude == 0.5 and instance.environment.wave.period == 5.0
        assets = os.path.join(str(tmp_path), "runtime_assets")
        texts = [open(os.path.join(root, name), encoding="utf-8").read() for root, _, names in os.walk(assets) for name in names if name.endswith(".sdf")]
        assert any("gz-waves1-waves-model-system" in text for text in texts)
        assert any("gz-waves1-hydrodynamics-system" in text for text in texts)
        assert spec.label() == "gazebo-custom-replay-straight-waves-0.5m-5s-5m-1x"

    def test_the_compose_project_of_a_waves_run_has_only_the_characters_compose_allows(self):
        spec = StackRunSpec(GAZEBO, "straight", "5m", 20, 1, 1, "usv_navigation", control_layer=CUSTOM, waves=(0.5, 5.0))
        assert compose_project_name(spec, 1) == "calib-gazebo-custom-usv-navigation-straight-waves-0-5m-5s-5m-1x-1"

    def test_hull_motion_is_peak_to_peak_heave_roll_and_pitch(self):
        def hull(z, pitch_deg):
            half = np.radians(pitch_deg) / 2
            return type("Hull", (), {"z": z, "qx": 0.0, "qy": float(np.sin(half)), "qz": 0.0, "qw": float(np.cos(half))})()

        motion = HullMotion.from_odometry([hull(-0.1, -2.0), hull(0.3, 3.0), hull(0.0, 0.0)])
        assert motion.heave_m == pytest.approx(0.4)
        assert motion.pitch_deg == pytest.approx(5.0)
        assert motion.roll_deg == pytest.approx(0.0)

    def test_the_evidence_names_the_hull_motion(self):
        run = self.custom()
        for repeat in run.repeats:
            repeat.motion = HullMotion(heave_m=0.9, roll_deg=0.5, pitch_deg=8.5)
        (entry,) = run.entries()
        assert "heave m 0.900, pitch deg 8.50, roll deg 0.50" in entry.fields["evidence"]

    def test_the_evidence_names_the_drive(self):
        (entry,) = self.custom(drive="usv_navigation").entries()
        assert "usv_navigation drive" in entry.fields["evidence"]


class TestValidation:
    @pytest.mark.parametrize(
        "spec,message",
        [
            (StackRunSpec(ARDUPILOT_SIM, reference="loop"), "Unknown reference run 'loop'"),
            (StackRunSpec(ARDUPILOT_SIM, drive="fly"), "Unknown drive 'fly'"),
            (StackRunSpec(SimulationLayerId.KINEMATIC), "Docker measurements need ardupilot_sim or gazebo"),
            (StackRunSpec(ARDUPILOT_SIM, control_layer=CUSTOM), "the custom controller runs on gazebo"),
            (StackRunSpec(GAZEBO, drive="target", control_layer=CUSTOM), "the custom controller runs on gazebo with the replay or usv_navigation drive"),
        ],
    )
    def test_invalid_specs_are_rejected_before_anything_starts(self, spec, message, tmp_path):
        with pytest.raises(ValueError, match=message):
            measure_stack(spec, str(tmp_path))
        assert os.listdir(tmp_path) == []


@pytest.mark.docker
@pytest.mark.slow
class TestRealRun:
    """Needs Docker and the project's SITL image. Repeats an ArduPilot Sim run and checks the numbers the resolver would use."""

    def test_ardupilot_sim_replay_repeats_stay_close_and_track_the_speedup(self, tmp_path):
        spec = StackRunSpec(ARDUPILOT_SIM, "straight", "5m", 20, speedup=5, repeats=2)
        result = measure_stack(spec, str(tmp_path), base_host_port=15900)
        assert [repeat.error for repeat in result.repeats] == [None, None]
        assert result.tracks_request
        assert result.deviation is not None and result.deviation.max_m < 1.0
        (entry,) = result.entries()
        entry.parsed()
