"""The control node's settings, from the environment (deploy/control_node/.env through compose, or --env-file).

The compose service sets the listeners and folders itself; the database password comes from the .env file.
Worker nodes and the control node trust each other on the VPN, so there are no certificates, credentials or broker accounts.

    SCENEGEMS_CONTROL_NODE_ID               the control node's id, also the cluster id (required)
    SCENEGEMS_DATABASE_URL            Postgres of the job store and worker node registry (required)
    SCENEGEMS_API_LISTEN_HOST, _PORT          worker node API, plain HTTP (default 0.0.0.0:8443)
    SCENEGEMS_OPERATOR_LISTEN_HOST, _PORT     workbench gateway and operator API (default 127.0.0.1:5174)
    SCENEGEMS_OPERATOR_ALLOWED_ORIGINS  browser origins the operator API allows (CORS), comma separated; the web UI's
                                      dev server by default (http://localhost:5173,http://127.0.0.1:5173)
    SCENEGEMS_RELEASE_MANIFEST        release.json of the release the control node runs (cluster/release); its
                                      image fingerprints are the ones the control node requires of worker nodes and jobs
    SCENEGEMS_ARTIFACT_DIR            the artifact store's folder (default /var/lib/scenegems/artifacts)
    SCENEGEMS_ARTIFACT_MAX_BYTES      largest artifact a worker node may upload, uncompressed (default 256 MiB)
    SCENEGEMS_ARTIFACT_SWEEP_INTERVAL_S  how often unreferenced artifacts are deleted (default 600; 0 turns the sweep off)
    SCENEGEMS_ARTIFACT_SWEEP_GRACE_S  how long an unreferenced artifact is kept after its last use (default 3600)
    SCENEGEMS_BROKER_HOST, _PORT      the cluster broker as the control node dials it (compose: cluster-broker, 1883); when
                                      the host is set the live channel observes pools

The control node starts no containers: it has no Docker socket, and every subsystem runs on a worker node.
"""

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping, Optional, Tuple

from scenegems_tool.cluster.scope_names import is_scope_name
from scenegems_tool.persistence.database import DATABASE_URL_ENV

DEFAULT_ARTIFACT_DIR = Path("/var/lib/scenegems/artifacts")
DEFAULT_OPERATOR_ALLOWED_ORIGINS = ("http://localhost:5173", "http://127.0.0.1:5173")


class SettingMissing(ValueError):
    pass


@dataclass(frozen=True)
class Listener:
    host: str
    port: int


@dataclass(frozen=True)
class ControlNodeSettings:
    control_node_id: str
    database_url: str = field(repr=False)
    worker_node_api: Listener = Listener("0.0.0.0", 8443)
    operator: Listener = Listener("127.0.0.1", 5174)
    release_manifest: Optional[Path] = None
    operator_allowed_origins: Tuple[str, ...] = DEFAULT_OPERATOR_ALLOWED_ORIGINS
    artifacts: "ArtifactSettings" = field(default_factory=lambda: ArtifactSettings())
    broker: Optional["BrokerClientSettings"] = None  # the control node's own broker login, for observing pools

    @classmethod
    def from_environment(cls, environ: Optional[Mapping[str, str]] = None) -> "ControlNodeSettings":
        environ = os.environ if environ is None else environ
        control_node_id = _required(environ, "SCENEGEMS_CONTROL_NODE_ID")
        if not is_scope_name(control_node_id):
            raise ValueError(f"SCENEGEMS_CONTROL_NODE_ID: {control_node_id!r} is not a control node id (1 to 63 lowercase letters, digits and hyphens)")
        release_manifest = environ.get("SCENEGEMS_RELEASE_MANIFEST", "").strip()
        return cls(
            control_node_id=control_node_id,
            database_url=_required(environ, DATABASE_URL_ENV),
            worker_node_api=_listener(environ, "SCENEGEMS_API", cls.worker_node_api),
            operator=_listener(environ, "SCENEGEMS_OPERATOR", cls.operator),
            release_manifest=Path(release_manifest) if release_manifest else None,
            operator_allowed_origins=parse_allowed_origins(environ.get("SCENEGEMS_OPERATOR_ALLOWED_ORIGINS", "")),
            artifacts=ArtifactSettings.from_environment(environ),
            broker=BrokerClientSettings.from_environment(environ),
        )


@dataclass(frozen=True)
class ArtifactSettings:
    """The artifact store (persistence/artifacts/) and its sweep of unreferenced artifacts."""

    folder: Path = DEFAULT_ARTIFACT_DIR
    max_bytes: int = 256 * 1024 * 1024
    sweep_interval_s: float = 600.0  # 0: no sweep
    sweep_grace_s: float = 3600.0

    def __post_init__(self) -> None:
        if self.max_bytes <= 0 or self.sweep_interval_s < 0 or self.sweep_grace_s < 0:
            raise ValueError(f"invalid artifact settings: {self}")

    @classmethod
    def from_environment(cls, environ: Mapping[str, str]) -> "ArtifactSettings":
        folder = environ.get("SCENEGEMS_ARTIFACT_DIR", "").strip()
        return cls(
            folder=Path(folder) if folder else cls.folder,
            max_bytes=int(_number(environ, "SCENEGEMS_ARTIFACT_MAX_BYTES", cls.max_bytes, int)),
            sweep_interval_s=_number(environ, "SCENEGEMS_ARTIFACT_SWEEP_INTERVAL_S", cls.sweep_interval_s, float),
            sweep_grace_s=_number(environ, "SCENEGEMS_ARTIFACT_SWEEP_GRACE_S", cls.sweep_grace_s, float),
        )


def parse_allowed_origins(text: str) -> Tuple[str, ...]:
    """The origins of a comma separated list, without blanks and trailing slashes; the defaults for an empty list."""
    origins = tuple(dict.fromkeys(item.strip().rstrip("/") for item in text.split(",") if item.strip()))
    return origins or DEFAULT_OPERATOR_ALLOWED_ORIGINS


@dataclass(frozen=True)
class BrokerClientSettings:
    """Where the control node dials its own cluster broker (the live channel's observation hub): plain and anonymous."""

    host: str
    port: int = 1883

    @classmethod
    def from_environment(cls, environ: Mapping[str, str]) -> Optional["BrokerClientSettings"]:
        """None unless the broker host is set."""
        host = environ.get("SCENEGEMS_BROKER_HOST", "").strip()
        if not host:
            return None
        return cls(host=host, port=int(_number(environ, "SCENEGEMS_BROKER_PORT", cls.port, int)))


def _number(environ: Mapping[str, str], name: str, default, parse):
    text = environ.get(name, "").strip()
    if not text:
        return default
    try:
        return parse(text)
    except ValueError:
        raise ValueError(f"{name} must be a number, got {text!r}") from None


def _required(environ: Mapping[str, str], name: str) -> str:
    value = environ.get(name, "").strip()
    if not value:
        raise SettingMissing(f"{name} is not set; see deploy/control_node/.env.example")
    return value


def _listener(environ: Mapping[str, str], prefix: str, default: Listener) -> Listener:
    host = environ.get(f"{prefix}_LISTEN_HOST", "").strip() or default.host
    port = environ.get(f"{prefix}_LISTEN_PORT", "").strip()
    return Listener(host, int(port) if port else default.port)
