import pytest

from scenegems_tool.persistence.stores import NewCalibrationResult

pytestmark = pytest.mark.postgres

STACK = {"asv_system": "replay", "control_layer": "ardupilot", "simulation_layer": "ardupilot_sim", "adapter": "replay_mavlink_lockstep"}
FINGERPRINTS = {"scenegems-sitl": "fp-sitl", "scenegems-simulation": "fp-execution"}
CALM = {"wind_vector": None, "waves": None, "speedup": 5}


def _result(**fields):
    values = dict(stack=STACK, fingerprints=FINGERPRINTS, environment=CALM, reference_scenario="straight_leg", repeats=5, exact=False, deviation_bound_m=0.071, envelope={"max_m": 0.071})
    values.update(fields)
    return NewCalibrationResult(**values)


def test_upsert_and_find(stores, clock):
    stored = stores.calibrations.upsert(_result())
    assert (stored.repeats, stored.exact, stored.deviation_bound_m, stored.envelope) == (5, False, 0.071, {"max_m": 0.071})
    # key order does not matter for the lookup
    reordered_stack = dict(reversed(list(STACK.items())))
    assert stores.calibrations.find(reordered_stack, dict(reversed(list(FINGERPRINTS.items())))) == [stored]
    assert stores.calibrations.find(STACK, FINGERPRINTS, environment=CALM, reference_scenario="straight_leg") == [stored]
    assert stores.calibrations.find(STACK, {"scenegems-sitl": "older"}) == []
    assert stores.calibrations.find(STACK, FINGERPRINTS, environment=dict(CALM, speedup=20)) == []


def test_a_new_measurement_replaces_the_old_one(stores, clock):
    first = stores.calibrations.upsert(_result())
    clock.advance(100)
    second = stores.calibrations.upsert(_result(repeats=10, deviation_bound_m=0.08, note="rerun"))
    assert second.calibration_id == first.calibration_id
    assert (second.repeats, second.deviation_bound_m, second.note, second.created_at, second.updated_at) == (10, 0.08, "rerun", first.created_at, clock.now)
    assert stores.calibrations.list_results() == [second]


def test_results_per_reference_scenario_and_environment(stores):
    straight = stores.calibrations.upsert(_result())
    turn = stores.calibrations.upsert(_result(reference_scenario="turn", deviation_bound_m=12.85))
    fast = stores.calibrations.upsert(_result(environment=dict(CALM, speedup=20), deviation_bound_m=0.311))
    assert stores.calibrations.find(STACK, FINGERPRINTS) == [straight, fast, turn]  # by reference scenario, then age
    assert stores.calibrations.find(STACK, FINGERPRINTS, environment=CALM) == [straight, turn]


def test_an_exact_stack(stores):
    exact = stores.calibrations.upsert(_result(stack={"asv_system": "replay", "control_layer": "none", "simulation_layer": "kinematic"}, exact=True, deviation_bound_m=None, envelope=None))
    assert (exact.exact, exact.deviation_bound_m, exact.envelope) == (True, None, {})


def test_a_calibration_needs_a_repeat(stores):
    with pytest.raises(ValueError):
        stores.calibrations.upsert(_result(repeats=0))
