import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from utils.image_names import DEFAULT_IMAGE_TAG, image_repository, image_tag, tagged, with_tag

SRC = Path(__file__).resolve().parents[2]


def test_the_tag_is_latest_unless_set(monkeypatch):
    monkeypatch.delenv("SCENEGEMS_IMAGE_TAG", raising=False)
    assert image_tag() == DEFAULT_IMAGE_TAG == "latest"
    monkeypatch.setenv("SCENEGEMS_IMAGE_TAG", " abc123-dirty ")
    assert image_tag() == "abc123-dirty" and tagged("scenegems-node") == "scenegems-node:abc123-dirty"
    monkeypatch.setenv("SCENEGEMS_IMAGE_TAG", "")
    assert image_tag() == "latest"


@pytest.mark.parametrize("tag", ["a b", "-x", "x" * 129, "x:y"])
def test_a_malformed_tag_fails(monkeypatch, tag):
    monkeypatch.setenv("SCENEGEMS_IMAGE_TAG", tag)
    with pytest.raises(ValueError, match="SCENEGEMS_IMAGE_TAG"):
        image_tag()


@pytest.mark.parametrize(
    "name, repository",
    [
        ("scenegems-node:latest", "scenegems-node"),
        ("scenegems-node", "scenegems-node"),
        ("localhost:5000/a/b:v1", "localhost:5000/a/b"),
        ("localhost:5000/a", "localhost:5000/a"),
        ("a@sha256:00", "a"),
        ("a:v1@sha256:00", "a"),
    ],
)
def test_the_repository_is_the_name_without_tag_and_digest(name, repository):
    assert image_repository(name) == repository


def test_with_tag_replaces_the_tag():
    assert with_tag("scenegems-node:latest", "abc") == "scenegems-node:abc" and with_tag("localhost:5000/a", "v2") == "localhost:5000/a:v2"


SCRIPT = """
import json
from scenegems_tool.cluster.fingerprints.components import component_images
from scenegems_tool.cluster.node.subsystem import Subsystem, subsystem_image
from scenegems_tool.vessel_stack.control_layers.ardupilot.ardupilot_specs import ARDUAGENT_CONTAINER, MAVPROXY_CONTAINER, SITL_CONTAINER
from scenegems_tool.vessel_stack.simulation_layers.gazebo.gazebo_specs import GAZEBO_CONTAINER
images = [image for images in component_images().values() for image in images]
images += [subsystem_image(subsystem) for subsystem in Subsystem]
images += [container.default_image for container in (ARDUAGENT_CONTAINER, MAVPROXY_CONTAINER, SITL_CONTAINER, GAZEBO_CONTAINER)]
print(json.dumps({"images": sorted(set(images)), "sitl": SITL_CONTAINER.image}))
"""


def test_scenegems_image_tag_names_every_image_scenegems_builds():
    environ = {key: value for key, value in os.environ.items() if not key.endswith("_IMAGE")}
    environ.update(SCENEGEMS_IMAGE_TAG="rev9", PYTHONPATH=str(SRC))
    completed = subprocess.run([sys.executable, "-c", SCRIPT], capture_output=True, text=True, env=environ, cwd=SRC, check=True)
    found = json.loads(completed.stdout.strip().splitlines()[-1])
    assert (
        len(found["images"]) == 10
        and "scenegems-design-space-exploration-subsystem:rev9" in found["images"]
        and "scenegems-usv-navigation:rev9" in found["images"]
        and all(image.startswith("scenegems-") and image.endswith(":rev9") for image in found["images"])
    ), found
    assert found["sitl"] == "${SITL_IMAGE:-scenegems-ardupilot-sitl:rev9}", "a variable still overrides the image"
