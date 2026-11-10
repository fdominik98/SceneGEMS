"""AdapterRegistry: registration rules, defaults and alternatives, ruled-out connections, runtime bindings."""

import pytest

from scenegems_tool.vessel_stack.contracts.adapter_spec import AdapterSpec, LayerSpec, UnsupportedConnection
from scenegems_tool.vessel_stack.contracts.roles import AsvSystemId, ControlLayerId, LayerRef, SimulationLayerId
from scenegems_tool.vessel_stack.registry.adapter_registry import AdapterRegistry
from scenegems_tool.vessel_stack.registry.catalog import default_registry
from scenegems_tool.vessel_stack.registry.measured_capabilities import parse_capability_measurement

REPLAY = LayerRef.of(AsvSystemId.REPLAY)
NONE = LayerRef.of(ControlLayerId.NONE)
ARDUPILOT = LayerRef.of(ControlLayerId.ARDUPILOT)
KINEMATIC = LayerRef.of(SimulationLayerId.KINEMATIC)


def adapter(adapter_id: str, source: LayerRef = REPLAY, target: LayerRef = NONE) -> AdapterSpec:
    return AdapterSpec(id=adapter_id, source=source, target=target, description=adapter_id)


@pytest.fixture
def registry() -> AdapterRegistry:
    registry = AdapterRegistry()
    registry.register_layer(LayerSpec(layer=REPLAY, description="replay"))
    registry.register_layer(LayerSpec(layer=NONE, description="none"))
    return registry


class TestRegistration:
    def test_registered_layer_is_found(self, registry):
        assert registry.layer(REPLAY).description == "replay"
        assert registry.layer(KINEMATIC) is None

    def test_duplicate_layer_fails(self, registry):
        with pytest.raises(ValueError, match="Spec asv_system/replay is already registered"):
            registry.register_layer(LayerSpec(layer=REPLAY, description="again"))

    def test_duplicate_adapter_id_fails(self, registry):
        registry.register_adapter(adapter("first"))
        with pytest.raises(ValueError, match="Spec first is already registered"):
            registry.register_adapter(adapter("first", ARDUPILOT, KINEMATIC), default=True)

    def test_adapter_and_layer_ids_share_one_namespace(self, registry):
        with pytest.raises(ValueError, match="already registered"):
            registry.register_adapter(adapter("asv_system/replay", ARDUPILOT, KINEMATIC))

    def test_first_adapter_of_a_connection_is_the_default(self, registry):
        registry.register_adapter(adapter("first"))
        assert registry.adapter_between(REPLAY, NONE).id == "first"

    def test_second_adapter_on_a_connection_must_say_whether_it_is_the_default(self, registry):
        registry.register_adapter(adapter("first"))
        with pytest.raises(ValueError, match="both connect asv_system/replay to control_layer/none; pass default=True or default=False"):
            registry.register_adapter(adapter("second"))

    def test_alternative_does_not_replace_the_default(self, registry):
        registry.register_adapter(adapter("first"))
        registry.register_adapter(adapter("second"), default=False)
        assert registry.adapter_between(REPLAY, NONE).id == "first"
        assert [spec.id for spec in registry.adapters_between(REPLAY, NONE)] == ["first", "second"]

    def test_new_default_goes_first(self, registry):
        registry.register_adapter(adapter("first"))
        registry.register_adapter(adapter("second"), default=True)
        assert registry.adapter_between(REPLAY, NONE).id == "second"
        assert [spec.id for spec in registry.adapters_between(REPLAY, NONE)] == ["second", "first"]

    def test_selecting_an_alternative_by_id(self, registry):
        registry.register_adapter(adapter("first"))
        registry.register_adapter(adapter("second"), default=False)
        assert registry.adapter_between(REPLAY, NONE, ["second"]).id == "second"

    def test_selecting_an_adapter_of_another_connection_falls_back_to_the_default(self, registry):
        registry.register_adapter(adapter("first"))
        registry.register_adapter(adapter("elsewhere", ARDUPILOT, KINEMATIC))
        assert registry.adapter_between(REPLAY, NONE, ["elsewhere"]).id == "first"

    def test_connection_without_adapter(self, registry):
        assert registry.adapter_between(REPLAY, KINEMATIC) is None
        assert registry.adapters_between(REPLAY, KINEMATIC) == []

    def test_has_adapter_and_lookup_by_id(self, registry):
        registry.register_adapter(adapter("first"))
        assert registry.has_adapter("first")
        assert not registry.has_adapter("missing")
        assert registry.adapter("first").id == "first"
        with pytest.raises(KeyError):
            registry.adapter("missing")

    def test_adapters_lists_alternatives_too(self, registry):
        registry.register_adapter(adapter("first"))
        registry.register_adapter(adapter("second"), default=False)
        assert {spec.id for spec in registry.adapters} == {"first", "second"}


class TestUnsupportedConnections:
    def test_declared_connection_has_a_reason(self, registry):
        registry.declare_unsupported(UnsupportedConnection(REPLAY, KINEMATIC, "no way"))
        assert registry.unsupported_between(REPLAY, KINEMATIC).reason == "no way"
        assert registry.unsupported_between(REPLAY, NONE) is None

    def test_connection_with_an_adapter_cannot_be_declared_unsupported(self, registry):
        registry.register_adapter(adapter("first"))
        with pytest.raises(ValueError, match="has adapter first and cannot be declared unsupported"):
            registry.declare_unsupported(UnsupportedConnection(REPLAY, NONE, "no way"))

    def test_adapter_on_an_unsupported_connection_cannot_be_registered(self, registry):
        registry.declare_unsupported(UnsupportedConnection(REPLAY, NONE, "no way"))
        with pytest.raises(ValueError, match="which is declared unsupported"):
            registry.register_adapter(adapter("first"))


class TestRuntimeBinding:
    def test_runtime_loader_is_called_on_lookup_only(self, registry):
        calls = []

        def loader():
            calls.append(1)
            return "runtime class"

        registry.register_adapter(adapter("first"), runtime=loader)
        assert calls == []
        assert registry.runtime("first") == "runtime class"
        assert calls == [1]

    def test_missing_runtime_is_a_lookup_error(self, registry):
        registry.register_adapter(adapter("first"))
        with pytest.raises(LookupError, match="first has no runtime implementation"):
            registry.runtime("first")

    def test_bind_runtime_after_registration(self, registry):
        registry.register_adapter(adapter("first"))
        registry.bind_runtime("first", lambda: 5)
        assert registry.runtime("first") == 5

    def test_the_docker_contributor_is_bound_apart_from_the_runtime_and_loaded_on_first_use(self, registry):
        calls = []

        def loader():
            calls.append(1)
            return "docker class"

        registry.register_adapter(adapter("first"), runtime=lambda: "runtime class", docker=loader)
        assert calls == []
        assert registry.docker("first") == "docker class" and registry.runtime("first") == "runtime class"
        assert calls == [1]

    def test_a_spec_without_a_container_has_no_docker_contributor(self, registry):
        registry.register_adapter(adapter("first"), runtime=lambda: "runtime class")
        assert registry.docker("first") is None

    def test_bind_runtime_to_an_unknown_spec_fails(self, registry):
        with pytest.raises(KeyError, match="No spec missing is registered"):
            registry.bind_runtime("missing", lambda: 5)


class TestMeasurements:
    def test_measurement_replaces_the_declared_capabilities(self):
        measurements = {"first": parse_capability_measurement("first", {"repeatability_tier": "none", "max_speedup": 3, "notes": {"max_speedup": "bench"}})}
        registry = AdapterRegistry(measurements)
        registry.register_layer(LayerSpec(layer=REPLAY, description="replay"))
        spec = registry.register_adapter(adapter("first"))
        assert spec.capabilities.max_speedup == 3
        assert spec.note_for("max_speedup") == "bench"
        assert registry.measurement("first") is measurements["first"]

    def test_unmatched_measurement_fails_the_check(self, registry):
        registry = AdapterRegistry({"nothing": parse_capability_measurement("nothing", {})})
        with pytest.raises(ValueError, match="nothing"):
            registry.check_measurements()


class TestDefaultRegistry:
    def test_is_built_once(self):
        assert default_registry() is default_registry()

    def test_every_available_runtime_loader_resolves_without_docker_or_mqtt(self):
        registry = default_registry()
        for spec_id in ("simulation_layer/kinematic", "replay_state_follower", "usv_navigation_in_process"):
            assert registry.runtime(spec_id) is not None

    def test_lockstep_link_is_the_default_and_arduagent_the_alternative(self):
        registry = default_registry()
        assert [spec.id for spec in registry.adapters_between(REPLAY, ARDUPILOT)] == ["replay_mavlink_lockstep", "replay_arduagent_follower"]

    def test_every_ruled_out_connection_has_no_adapter(self):
        registry = default_registry()
        for source, target in ((NONE, LayerRef.of(SimulationLayerId.GAZEBO)), (ARDUPILOT, KINEMATIC)):
            assert registry.adapter_between(source, target) is None
            assert registry.unsupported_between(source, target) is not None


class TestOnBoardAsvSystem:
    ON_BOARD = LayerRef.of(AsvSystemId.ON_BOARD)

    def test_an_adapter_from_on_board_needs_a_layer_that_brings_asv_system(self, registry):
        registry.register_layer(LayerSpec(layer=self.ON_BOARD, description="on board"))
        with pytest.raises(ValueError, match="leaves the vessel to on board ASV system, but control_layer/none is not registered with on_board_asv_system"):
            registry.register_adapter(adapter("on_board_probe", self.ON_BOARD, NONE))

    def test_a_layer_that_brings_asv_system_accepts_it(self):
        registry = AdapterRegistry()
        hosting = LayerRef.of(ControlLayerId.REAL_VESSEL)
        registry.register_layer(LayerSpec(layer=self.ON_BOARD, description="on board"))
        registry.register_layer(LayerSpec(layer=hosting, description="hosts its own software", on_board_asv_system=True))
        assert registry.register_adapter(adapter("on_board_probe", self.ON_BOARD, hosting)).target == hosting

    def test_an_unregistered_target_is_refused_too(self):
        registry = AdapterRegistry()
        with pytest.raises(ValueError, match="on_board_asv_system"):
            registry.register_adapter(adapter("on_board_probe", self.ON_BOARD, NONE))
