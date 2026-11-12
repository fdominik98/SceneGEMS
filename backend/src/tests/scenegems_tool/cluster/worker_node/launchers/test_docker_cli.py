"""The Docker CLI wrappers that find a worker node's instances: what they ask Docker and what they make of its answer."""

from types import SimpleNamespace

from scenegems_tool.cluster.worker_node.instance_scope import INSTANCE_LABEL
from scenegems_tool.cluster.worker_node.launchers import docker_cli


def test_instances_are_found_by_the_start_of_their_containers_names(monkeypatch):
    calls = []

    def run(command, **options):
        calls.append(command)
        return SimpleNamespace(stdout="job-b-2\njob-a-1\njob-a-1\n\n", returncode=0)

    monkeypatch.setattr(docker_cli.subprocess, "run", run)
    keys = docker_cli.instance_keys_with_name_prefix("scenegems-m1-n1", "scenegems-m1-n1-simulation-subsystem-")
    assert keys == ["job-a-1", "job-b-2"], "each instance once, whatever the number of its containers"
    [command] = calls
    assert command[:3] == ["docker", "ps", "-a"], "stopped containers too"
    assert "label=com.docker.compose.project=scenegems-m1-n1" in command and f"label={INSTANCE_LABEL}" in command
    assert "name=^scenegems-m1-n1-simulation-subsystem-" in command, "from the start of the name: the subsystem's own container has no dash after it"
    assert command[command.index("--format") + 1] == f'{{{{.Label "{INSTANCE_LABEL}"}}}}'


def test_a_project_without_such_containers_has_no_instances(monkeypatch):
    monkeypatch.setattr(docker_cli.subprocess, "run", lambda command, **options: SimpleNamespace(stdout="", returncode=0))
    assert docker_cli.instance_keys_with_name_prefix("scenegems-m1-n1", "scenegems-m1-n1-simulation-subsystem-") == []
