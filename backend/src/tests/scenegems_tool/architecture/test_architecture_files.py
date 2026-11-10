"""The architecture files: written from the specs, read back for the API, rebuilt in memory when they are missing."""

import json

import pytest
import yaml

from scenegems_tool.architecture import architecture_files
from scenegems_tool.architecture.architecture_catalog import build_architecture_documents
from scenegems_tool.architecture.architecture_files import INDEX_FILE, architecture_view, read_architecture_files, start_architecture_files_writer, write_architecture_files
from scenegems_tool.architecture.architecture_model import SCHEMA_VERSION, to_plain
from scenegems_tool.cluster.protocol.jobs import JobType
from scenegems_tool.subsystems.subsystem_spec import MeasuredFacts, parse_measured_facts

DOCUMENT_IDS = ["design_space_exploration", "scene_generation", "trajectory_generation", "vessel_stack", "monitoring"]  # the chain, then what serves it


def test_the_catalog_builds_the_five_documents_in_chain_order():
    assert list(build_architecture_documents()) == DOCUMENT_IDS


def test_every_document_says_its_place_in_the_chain():
    documents = build_architecture_documents()
    assert [(document.role, document.step) for document in documents.values()] == [
        ("step", "Design space exploration"),
        ("step", "Scene generation"),
        ("step", "Trajectory generation"),
        ("step", "Simulation"),
        ("support", ""),
    ]
    assert all(document.takes and document.gives and document.job_types for document in documents.values())
    # every step gives what the next one takes, in the words the page joins them with
    assert (documents["design_space_exploration"].gives, documents["scene_generation"].takes) == ("FECs", "a FEC")
    assert (documents["scene_generation"].gives, documents["trajectory_generation"].takes) == ("a scene", "a scene")
    assert (documents["trajectory_generation"].gives, documents["vessel_stack"].takes) == ("trajectories", "trajectories")
    job_types = {member.value for member in JobType}
    assert all(set(document.job_types) <= job_types for document in documents.values())
    plain = to_plain(documents["monitoring"])
    assert (plain["role"], plain["step"], plain["job_types"]) == ("support", "", ["monitoring.post_hoc"])


def test_a_document_with_an_unknown_role_is_refused():
    import dataclasses

    document = build_architecture_documents()["monitoring"]
    with pytest.raises(ValueError, match="unknown role"):
        dataclasses.replace(document, role="extra").validate()


def test_one_file_per_document_and_an_index_are_written(tmp_path):
    written = write_architecture_files(str(tmp_path))
    assert [path.name for path in written] == [f"{document_id}.yaml" for document_id in DOCUMENT_IDS] + [INDEX_FILE]
    index = yaml.safe_load((tmp_path / INDEX_FILE).read_text(encoding="utf-8"))
    assert index["schema_version"] == SCHEMA_VERSION
    assert [entry["id"] for entry in index["documents"]] == DOCUMENT_IDS
    assert (tmp_path / "monitoring.yaml").read_text(encoding="utf-8").startswith("# Generated at control node startup")


def test_the_files_read_back_as_the_documents_they_were_built_from(tmp_path):
    write_architecture_files(str(tmp_path))
    view = read_architecture_files(str(tmp_path))
    assert view is not None
    documents = build_architecture_documents()
    assert [document["id"] for document in view["documents"]] == DOCUMENT_IDS
    assert view["documents"] == [to_plain(document) for document in documents.values()]
    json.dumps(view)  # whatever the API serves is JSON


def test_a_rewrite_after_a_change_is_picked_up_not_served_from_the_cache(tmp_path):
    write_architecture_files(str(tmp_path))
    before = read_architecture_files(str(tmp_path))
    assert read_architecture_files(str(tmp_path)) is before  # unchanged files: the cached view
    path = tmp_path / "monitoring.yaml"
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    document["title"] = "Changed"
    path.write_text(yaml.safe_dump(document), encoding="utf-8")
    after = read_architecture_files(str(tmp_path))
    assert after is not before and [item["title"] for item in after["documents"] if item["id"] == "monitoring"] == ["Changed"]


def test_missing_or_foreign_files_are_not_served(tmp_path):
    assert read_architecture_files(str(tmp_path / "nowhere")) is None
    write_architecture_files(str(tmp_path))
    (tmp_path / "scene_generation.yaml").unlink()
    assert read_architecture_files(str(tmp_path)) is None
    write_architecture_files(str(tmp_path))
    index = yaml.safe_load((tmp_path / INDEX_FILE).read_text(encoding="utf-8"))
    index["schema_version"] = SCHEMA_VERSION + 1
    (tmp_path / INDEX_FILE).write_text(yaml.safe_dump(index), encoding="utf-8")
    assert read_architecture_files(str(tmp_path)) is None


def test_without_files_the_view_is_built_in_memory(tmp_path):
    view = architecture_view(str(tmp_path / "nowhere"))
    assert [document["id"] for document in view["documents"]] == DOCUMENT_IDS and view["schema_version"] == SCHEMA_VERSION


def test_the_startup_writer_fills_the_folder_in_the_background(tmp_path):
    start_architecture_files_writer(str(tmp_path)).join(timeout=60)
    assert (tmp_path / INDEX_FILE).exists()


def test_a_folder_that_cannot_be_written_is_logged_not_raised(tmp_path, caplog):
    blocked = tmp_path / "file"
    blocked.write_text("not a folder", encoding="utf-8")
    start_architecture_files_writer(str(blocked / "inside")).join(timeout=60)
    assert "Could not write the architecture description files" in caplog.text


def test_the_default_folder_is_under_the_backend_assets():
    assert architecture_files.ARCHITECTURE_FOLDER.endswith("backend/assets/architecture")


def test_a_measured_entry_without_a_node_or_edge_fails_the_build():
    typo = {"monitoring/colregs_monitr": parse_measured_facts("monitoring/colregs_monitr", {"facts": [{"key": "k", "label": "K", "value": 1}]})}
    with pytest.raises(ValueError, match="unknown specs: monitoring/colregs_monitr"):
        build_architecture_documents(typo)


def test_measured_facts_are_added_to_the_node_they_are_keyed_by():
    measurements = {
        "monitoring/colregs_monitor": MeasuredFacts(parse_measured_facts("m", {"facts": [{"key": "rate", "label": "Rate", "value": 7, "unit": "scenes/s"}], "evidence": "today"}).facts, "today")
    }
    node = next(node for node in build_architecture_documents(measurements)["monitoring"].nodes if node.id == "monitoring/colregs_monitor")
    rate = next(fact for fact in node.facts if fact.key == "rate")
    assert rate.measured and rate.value == 7 and rate.unit == "scenes/s" and node.evidence == "today"
