"""Postgres for the tests of persistence/ and of the control node (cluster/control_node/), which share one server.

The server is SCENEGEMS_TEST_DATABASE_URL when set (its role needs CREATEDB), otherwise a
throwaway container started from the image the control node compose file uses. Every test gets
its own database: empty for the migration tests, or a copy of a template migrated once.
Without either server the postgres tests are skipped.
"""

import os
import time
from typing import Iterator
from uuid import uuid4

import pytest
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.engine import make_url

from scenegems_tool.cluster.release.roles import POSTGRES_IMAGE  # the image of deploy/control_node/docker-compose.yml
from scenegems_tool.persistence.database import create_database_engine, create_session_factory, normalize_database_url
from scenegems_tool.persistence.migrate import upgrade_database

TEST_DATABASE_URL_ENV = "SCENEGEMS_TEST_DATABASE_URL"
STARTUP_TIMEOUT_S = 60.0


def _wait_until_accepting(url: str) -> None:
    # The image's init phase listens on the Unix socket only, so a TCP connection means the final server
    engine = create_engine(url)
    deadline = time.monotonic() + STARTUP_TIMEOUT_S
    try:
        while True:
            try:
                with engine.connect() as connection:
                    connection.execute(text("SELECT 1"))
                return
            except Exception:
                if time.monotonic() > deadline:
                    raise
                time.sleep(0.25)
    finally:
        engine.dispose()


@pytest.fixture(scope="session")
def postgres_server_url() -> Iterator[str]:
    configured = os.environ.get(TEST_DATABASE_URL_ENV, "").strip()
    if configured:
        yield normalize_database_url(configured)
        return
    try:
        import docker

        client = docker.from_env()
        client.ping()
    except Exception as error:
        pytest.skip(f"no {TEST_DATABASE_URL_ENV} and Docker is not reachable: {error}")
    container = client.containers.run(
        POSTGRES_IMAGE,
        detach=True,
        remove=True,
        environment={"POSTGRES_USER": "scenegems", "POSTGRES_PASSWORD": "scenegems", "POSTGRES_DB": "scenegems"},
        ports={"5432/tcp": ("127.0.0.1", None)},
        tmpfs={"/var/lib/postgresql/data": "rw"},
        labels={"org.scenegems.purpose": "pytest-postgres"},
    )
    try:
        container.reload()
        port = container.ports["5432/tcp"][0]["HostPort"]
        url = f"postgresql+psycopg://scenegems:scenegems@127.0.0.1:{port}/scenegems"
        _wait_until_accepting(url)
        yield url
    finally:
        container.stop(timeout=5)


@pytest.fixture(scope="session")
def admin_engine(postgres_server_url) -> Iterator[Engine]:
    engine = create_engine(postgres_server_url, isolation_level="AUTOCOMMIT")
    yield engine
    engine.dispose()


def _create_database(admin_engine: Engine, template: str = None) -> str:
    name = f"scenegems_test_{uuid4().hex[:12]}"
    with admin_engine.connect() as connection:
        connection.execute(text(f'CREATE DATABASE "{name}"' + (f' TEMPLATE "{template}"' if template else "")))
    return name


def _drop_database(admin_engine: Engine, name: str) -> None:
    with admin_engine.connect() as connection:
        connection.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))


def _url_of(server_url: str, database: str) -> str:
    return make_url(server_url).set(database=database).render_as_string(hide_password=False)


@pytest.fixture
def empty_database_url(postgres_server_url, admin_engine) -> Iterator[str]:
    name = _create_database(admin_engine)
    yield _url_of(postgres_server_url, name)
    _drop_database(admin_engine, name)


@pytest.fixture(scope="session")
def migrated_template(postgres_server_url, admin_engine) -> Iterator[str]:
    name = _create_database(admin_engine)
    upgrade_database(_url_of(postgres_server_url, name))
    yield name
    _drop_database(admin_engine, name)


@pytest.fixture
def database_url(postgres_server_url, admin_engine, migrated_template) -> Iterator[str]:
    name = _create_database(admin_engine, template=migrated_template)
    yield _url_of(postgres_server_url, name)
    _drop_database(admin_engine, name)


@pytest.fixture
def engine(database_url) -> Iterator[Engine]:
    engine = create_database_engine(database_url, pool_size=32, max_overflow=0)
    yield engine
    engine.dispose()


@pytest.fixture
def session_factory(engine):
    return create_session_factory(engine)
