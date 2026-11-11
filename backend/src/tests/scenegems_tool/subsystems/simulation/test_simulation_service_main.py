"""The simulation subsystem's start: the stacks earlier tasks left behind are removed, and nothing else of the worker node."""

from scenegems_tool.subsystems.simulation import simulation_service_main
from scenegems_tool.subsystems.simulation.simulation_service_main import remove_leftover_stacks

PROJECT = "scenegems-m1-n1"


def test_the_stacks_of_earlier_tasks_are_removed_by_the_start_of_their_names(monkeypatch, tmp_path):
    asked, removed = [], []
    monkeypatch.setattr(simulation_service_main, "instance_keys_with_name_prefix", lambda project, prefix: asked.append((project, prefix)) or ["job-a-1", "job-b-2"])
    monkeypatch.setattr(simulation_service_main, "force_remove_instance", lambda project, key: removed.append(("containers", project, key)))
    monkeypatch.setattr(simulation_service_main, "remove_instance_networks", lambda project, key: removed.append(("networks", project, key)))
    for folder in (
        f"{PROJECT}-simulation-subsystem-joba",
        f"{PROJECT}-simulation-subsystem-jobb-2",
        f"{PROJECT}-simulation-subsystem",
        f"{PROJECT}-scene-generation-subsystem",
        "scenegems-m1-n2-simulation-subsystem-jobc",
    ):
        (tmp_path / folder / "gen").mkdir(parents=True)
    assert remove_leftover_stacks("m1", "n1", str(tmp_path)) == ["job-a-1", "job-b-2"]
    assert asked == [(PROJECT, f"{PROJECT}-simulation-subsystem-")], "the subsystem's own container has the name without the dash"
    assert removed == [("containers", PROJECT, "job-a-1"), ("networks", PROJECT, "job-a-1"), ("containers", PROJECT, "job-b-2"), ("networks", PROJECT, "job-b-2")]
    left = {folder.name for folder in tmp_path.iterdir()}
    assert left == {
        "scenegems-m1-n2-simulation-subsystem-jobc",
        f"{PROJECT}-scene-generation-subsystem",
        f"{PROJECT}-simulation-subsystem",
    }, "its own folder, the other pools and other worker nodes stay"


def test_a_machine_without_docker_or_without_the_folder_has_nothing_to_remove(monkeypatch, tmp_path):
    def no_docker(project, prefix):
        raise FileNotFoundError("docker")

    monkeypatch.setattr(simulation_service_main, "instance_keys_with_name_prefix", no_docker)
    assert remove_leftover_stacks("m1", "n1", str(tmp_path / "missing")) == []


def test_the_container_cleans_up_before_it_serves(monkeypatch):
    order = []
    monkeypatch.setenv("SCENEGEMS_CONTROL_NODE_ID", "m1")
    monkeypatch.setenv("SCENEGEMS_WORKER_NODE_ID", "n1")
    monkeypatch.setattr(simulation_service_main, "remove_leftover_stacks", lambda control_node_id, worker_node_id: order.append(("clean", control_node_id, worker_node_id)))
    monkeypatch.setattr(simulation_service_main, "service_from_environment", lambda service_class, name: (service_class.__name__, name))
    monkeypatch.setattr(simulation_service_main, "serve", lambda service: order.append(("serve", *service)))
    simulation_service_main.main()
    assert order == [("clean", "m1", "n1"), ("serve", "MqttSimulationService", "simulation-subsystem")]
