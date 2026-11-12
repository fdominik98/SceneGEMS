# scenegems-simulation-subsystem: the simulation subsystem's service and the runner of a run.
#
# The same image runs as two things. As the worker node's long-lived simulation subsystem (the default command) it
# takes run-simulation requests from the broker and starts each run's vessel stack through the host's Docker
# socket, so it carries the Docker CLI with the compose plugin, as the worker node daemon's image does. As the
# runner container of a run's stack it is given the job container main as its command and owns the run's clock.
FROM python:3.12-slim

WORKDIR /app

# The static Docker CLI and the compose plugin, for the machine's architecture (x86_64 or aarch64).
# The plugin binary also serves as `docker-compose`, which the launchers call.
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        ca-certificates \
        curl \
    && arch="$(uname -m)" \
    && curl -fsSL "https://download.docker.com/linux/static/stable/${arch}/docker-27.5.1.tgz" \
        | tar xz -C /usr/local/bin --strip-components=1 docker/docker \
    && mkdir -p /usr/local/lib/docker/cli-plugins \
    && curl -fsSL "https://github.com/docker/compose/releases/download/v2.32.4/docker-compose-linux-${arch}" \
        -o /usr/local/lib/docker/cli-plugins/docker-compose \
    && chmod +x /usr/local/lib/docker/cli-plugins/docker-compose \
    && ln -s /usr/local/lib/docker/cli-plugins/docker-compose /usr/local/bin/docker-compose \
    && rm -rf /var/lib/apt/lists/*

COPY deploy/images/simulation/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/pyproject.toml backend/setup.py backend/README.md ./
COPY backend/src ./src
COPY backend/assets/domain_config ./assets/domain_config
RUN pip install --no-cache-dir --no-deps -e .

ENV PYTHONUNBUFFERED=1

# The subsystem's service. A run's runner container is given its own command, the job runner
# (cluster/worker_node/launchers/per_job/job_container_io.py JOB_CONTAINER_MAIN).
CMD ["python", "-m", "scenegems_tool.subsystems.simulation.simulation_service_main"]
