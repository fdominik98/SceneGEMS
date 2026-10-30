"""deploy/scripts/docker-common.sh run on small repository copies."""

import os
import shutil
import subprocess
from pathlib import Path
from typing import Dict

import pytest

SCRIPTS = Path(__file__).resolve().parents[6] / "deploy" / "scripts"
_GIT_BASH_CANDIDATES = (r"C:\Program Files\Git\bin\bash.exe", r"C:\Program Files (x86)\Git\bin\bash.exe")


def _find_bash() -> str:
    """bash for the scripts. On Windows the bash on the PATH may be WSL's, so Git Bash is preferred."""
    override = os.environ.get("SCENEGEMS_BASH")
    if override:
        return override
    for candidate in _GIT_BASH_CANDIDATES:
        if os.path.exists(candidate):
            return candidate
    found = shutil.which("bash")
    if found is None:
        raise RuntimeError("bash is needed to run the build scripts; set SCENEGEMS_BASH")
    return found


def _parse_listing(text: str) -> Dict[str, str]:
    """The 'image fingerprint' lines printed by build.sh --fingerprints."""
    return dict(line.split() for line in text.splitlines() if len(line.split()) == 2)


try:
    BASH = _find_bash()
except RuntimeError:
    BASH = None

pytestmark = pytest.mark.skipif(BASH is None, reason="needs bash")


def _make_repo(root: Path, eol: str = "\n", name: str = "app.py", pins: str = "FOO_COMMIT=abc\n") -> Path:
    (root / "deploy" / "scripts").mkdir(parents=True)
    shutil.copy(SCRIPTS / "docker-common.sh", root / "deploy" / "scripts" / "docker-common.sh")
    (root / "deploy" / "images").mkdir(parents=True)
    (root / "deploy" / "images" / "upstream_pins.env").write_bytes(pins.replace("\n", eol).encode())
    image = root / "deploy" / "images" / "demo"
    (image / "src").mkdir(parents=True)
    (image / "Dockerfile").write_bytes("FROM scratch\nARG FOO_COMMIT\nCOPY src /src\n".replace("\n", eol).encode())
    (image / "src" / name).write_bytes("print('hi')\n\nprint('there')\n".replace("\n", eol).encode())
    (image / "src" / "data.bin").write_bytes(b"\x00\x01\r\n\x02")
    (image / "src" / "empty.txt").write_bytes(b"")
    return root


def _fingerprint(root: Path) -> str:
    script = 'source deploy/scripts/docker-common.sh; docker_common_init; fingerprint_image_inputs "$REPO_ROOT/deploy/images/demo/Dockerfile" "$REPO_ROOT/deploy/images/demo"'
    completed = subprocess.run([BASH, "-c", script], cwd=root, capture_output=True, text=True, check=True)
    return completed.stdout.strip()


def test_crlf_and_lf_copies_give_the_same_fingerprint(tmp_path):
    lf = _fingerprint(_make_repo(tmp_path / "lf", "\n"))
    crlf = _fingerprint(_make_repo(tmp_path / "crlf", "\r\n"))
    assert lf == crlf and len(lf) == 64


def test_the_location_of_the_checkout_does_not_matter(tmp_path):
    assert _fingerprint(_make_repo(tmp_path / "a")) == _fingerprint(_make_repo(tmp_path / "deeper" / "env" / "b"))


def test_content_file_name_and_pins_change_the_fingerprint(tmp_path):
    base = _fingerprint(_make_repo(tmp_path / "base"))
    assert _fingerprint(_make_repo(tmp_path / "renamed", name="other.py")) != base
    assert _fingerprint(_make_repo(tmp_path / "pins", pins="FOO_COMMIT=def\n")) != base
    edited = _make_repo(tmp_path / "edited")
    (edited / "deploy" / "images" / "demo" / "src" / "app.py").write_text("print('changed')\n")
    assert _fingerprint(edited) != base


def test_a_pin_the_dockerfile_does_not_declare_leaves_the_fingerprint_alone(tmp_path):
    root = _make_repo(tmp_path / "undeclared")
    (root / "deploy" / "images" / "demo" / "Dockerfile").write_text("FROM scratch\n")
    before = _fingerprint(root)
    (root / "deploy" / "images" / "upstream_pins.env").write_text("FOO_COMMIT=changed\n")
    assert _fingerprint(root) == before


@pytest.mark.slow
def test_build_script_lists_a_fingerprint_for_every_image():
    root = SCRIPTS.parents[1]
    completed = subprocess.run([BASH, (SCRIPTS / "build.sh").as_posix(), "--fingerprints"], cwd=root, capture_output=True, text=True, check=True)
    listing = _parse_listing(completed.stdout)
    assert "scenegems-master-api:latest" in listing and "scenegems-ardupilot-sitl:latest" in listing
    assert all(len(value) == 64 for value in listing.values())
