import asyncio

import pytest

from scenegems_tool.cluster.control_node import server
from scenegems_tool.cluster.control_node.control_node_artifacts import ControlNodeArtifacts
from scenegems_tool.cluster.control_node.settings import ArtifactSettings, ControlNodeSettings
from scenegems_tool.persistence.artifacts.file_artifact_store import FileArtifactStore
from scenegems_tool.persistence.artifacts.recorded_artifacts import RecordedArtifacts
from tests.scenegems_tool.persistence.artifacts.fake_artifact_records import InMemoryArtifactRecords
from tests.scenegems_tool.persistence.stores.builders import ManualClock


@pytest.fixture
def clock():
    return ManualClock()


@pytest.fixture
def artifacts(tmp_path, clock):
    return RecordedArtifacts(FileArtifactStore(tmp_path / "artifacts"), InMemoryArtifactRecords(clock))


def test_the_sweep_timer_deletes_unreferenced_artifacts_each_round(artifacts, clock, monkeypatch):
    stored = artifacts.put(b'{"old":true}', "scene", "application/json")
    clock.advance(120)
    control_node_artifacts = ControlNodeArtifacts(artifacts, sweep_interval_s=0.01, sweep_grace_s=60)
    rounds = []
    sweep = artifacts.sweep
    monkeypatch.setattr(artifacts, "sweep", lambda grace_s: rounds.append(grace_s) or sweep(grace_s))

    async def run():
        control_node_artifacts.start_sweep()
        control_node_artifacts.start_sweep()  # once only
        while len(rounds) < 2:
            await asyncio.sleep(0.01)
        await control_node_artifacts.stop_sweep()
        await control_node_artifacts.stop_sweep()

    asyncio.run(run())
    assert rounds[:2] == [60, 60] and not artifacts.store.exists(stored.stored.sha256)


def test_a_failed_round_does_not_end_the_timer(artifacts, monkeypatch):
    control_node_artifacts = ControlNodeArtifacts(artifacts, sweep_interval_s=0.01)
    calls = []

    def failing(grace_s):
        calls.append(grace_s)
        raise ConnectionError("database restarting")

    monkeypatch.setattr(artifacts, "sweep", failing)

    async def run():
        control_node_artifacts.start_sweep()
        while len(calls) < 3:
            await asyncio.sleep(0.01)
        await control_node_artifacts.stop_sweep()

    asyncio.run(run())
    assert len(calls) >= 3


def test_an_interval_of_zero_turns_the_sweep_off(artifacts):
    control_node_artifacts = ControlNodeArtifacts(artifacts, sweep_interval_s=0)

    async def run():
        control_node_artifacts.start_sweep()
        assert control_node_artifacts._task is None
        await control_node_artifacts.stop_sweep()

    asyncio.run(run())


def test_the_server_builds_the_store_on_the_artifact_folder(tmp_path):
    settings = ControlNodeSettings(control_node_id="lab-control-node", database_url="postgresql+psycopg://x@localhost/x", artifacts=ArtifactSettings(tmp_path / "artifacts", 1000, 30, 90))
    built = server.build_artifacts(settings, sessions=None)
    assert isinstance(built.artifacts.store, FileArtifactStore) and built.artifacts.store.root == tmp_path / "artifacts"
    assert (built.max_bytes, built.sweep_interval_s, built.sweep_grace_s) == (1000, 30, 90)
    assert (tmp_path / "artifacts" / ".incoming").is_dir()


def test_the_worker_node_api_runs_the_sweep_with_its_timers(plane, artifacts):
    from starlette.testclient import TestClient

    from scenegems_tool.cluster.control_node.api.control_node_apps import create_worker_node_api_app

    for run_timers in (True, False):
        control_node_artifacts = ControlNodeArtifacts(artifacts, sweep_interval_s=3600)
        with TestClient(create_worker_node_api_app(plane, run_timers=run_timers, artifacts=control_node_artifacts)):
            assert (control_node_artifacts._task is not None) == run_timers
        assert control_node_artifacts._task is None


def test_a_round_drops_the_expired_upload_holds_before_it_lists_unreferenced_artifacts(artifacts, clock):
    from datetime import timedelta

    stored = artifacts.put(b'{"upload":true}', "scene", "application/json")
    sha256 = stored.stored.sha256
    artifacts.records.add_upload_reference(sha256, clock() + timedelta(hours=24))
    control_node_artifacts = ControlNodeArtifacts(artifacts, sweep_grace_s=60)

    clock.advance(3600 * 23)  # the hold has not expired: nothing is unreferenced
    assert asyncio.run(control_node_artifacts.sweep_once()) == [] and artifacts.store.exists(sha256)

    clock.advance(3600 * 2)  # expired: the round drops the hold, which counts as a use, so the grace period starts now
    assert asyncio.run(control_node_artifacts.sweep_once()) == [] and artifacts.store.exists(sha256)
    assert artifacts.records.calls.count("remove_expired_uploads") == 2

    clock.advance(61)
    assert asyncio.run(control_node_artifacts.sweep_once()) == [sha256] and not artifacts.store.exists(sha256)


def test_an_upload_a_campaign_took_over_survives_the_end_of_its_hold(artifacts, clock):
    from datetime import timedelta

    from scenegems_tool.persistence.schema import ArtifactHolderKind

    sha256 = artifacts.put(b'{"upload":true}', "scene", "application/json").stored.sha256
    artifacts.records.add_upload_reference(sha256, clock() + timedelta(hours=24))
    artifacts.records.add_reference(sha256, ArtifactHolderKind.CAMPAIGN, "c1", "input:0", "c1")
    clock.advance(3600 * 48)
    assert asyncio.run(ControlNodeArtifacts(artifacts, sweep_grace_s=60).sweep_once()) == [] and artifacts.store.exists(sha256)


def test_a_round_also_deletes_old_files_without_a_record(artifacts, clock):
    import os
    import time

    unreferenced = artifacts.put(b'{"unreferenced":true}', "scene", "application/json").stored.sha256
    orphan = artifacts.store.put(b'{"orphan":true}').sha256
    then = time.time() - 120
    os.utime(artifacts.store.path(orphan), (then, then))
    clock.advance(120)
    assert asyncio.run(ControlNodeArtifacts(artifacts, sweep_grace_s=60).sweep_once()) == [unreferenced, orphan]
    assert not artifacts.store.exists(unreferenced) and not artifacts.store.exists(orphan)
    assert artifacts.records.calls[-2:] == ["delete_unreferenced", "existing_hashes"]  # records first, then the files without one


def test_the_hold_is_dropped_before_the_sweep_lists(artifacts, clock, monkeypatch):
    from datetime import timedelta

    sha256 = artifacts.put(b'{"upload":true}', "scene", "application/json").stored.sha256
    artifacts.records.add_upload_reference(sha256, clock() + timedelta(hours=1))
    clock.advance(7200)
    order = []
    sweep = artifacts.sweep
    monkeypatch.setattr(artifacts, "sweep", lambda grace_s: order.append(("sweep", list(artifacts.records.calls))) or sweep(grace_s))
    asyncio.run(ControlNodeArtifacts(artifacts, sweep_grace_s=60).sweep_once())
    assert order[0][0] == "sweep" and order[0][1][-1] == "remove_expired_uploads"
