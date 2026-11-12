# scenegems-worker-node: the worker node daemon (python -m scenegems_tool.cluster.worker_node.daemon).
#
# Python, the Docker CLI with the compose plugin, Git and the backend source. The daemon starts the
# worker node's subsystems through the host's Docker socket and passes every job to one of them as a
# request over the cluster's broker; it runs no job itself.
# deploy/worker_node/docker-compose.yml starts it with the socket, the repository and its volumes.
FROM python:3.12-slim

WORKDIR /app

# The static Docker CLI and the compose plugin, for the machine's architecture (x86_64 or aarch64).
# The plugin binary also serves as `docker-compose`, which the launchers call.
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        ca-certificates \
        curl \
        git \
    && arch="$(uname -m)" \
    && curl -fsSL "https://download.docker.com/linux/static/stable/${arch}/docker-27.5.1.tgz" \
        | tar xz -C /usr/local/bin --strip-components=1 docker/docker \
    && mkdir -p /usr/local/lib/docker/cli-plugins \
    && curl -fsSL "https://github.com/docker/compose/releases/download/v2.32.4/docker-compose-linux-${arch}" \
        -o /usr/local/lib/docker/cli-plugins/docker-compose \
    && chmod +x /usr/local/lib/docker/cli-plugins/docker-compose \
    && ln -s /usr/local/lib/docker/cli-plugins/docker-compose /usr/local/bin/docker-compose \
    && rm -rf /var/lib/apt/lists/*

COPY deploy/images/worker_node/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/pyproject.toml backend/setup.py backend/README.md ./
COPY backend/src ./src
COPY backend/assets/domain_config ./assets/domain_config
COPY backend/assets/runtime_assets ./assets/runtime_assets
RUN pip install --no-cache-dir --no-deps -e .

ENV PYTHONPATH=/app/src \
    PYTHONUNBUFFERED=1

CMD ["python", "-m", "scenegems_tool.cluster.worker_node.daemon"]
