# scenegems-worker-node: the worker node daemon (python -m scenegems_tool.cluster.worker_node.daemon).
#
# Python, Git and the backend source. The daemon creates the worker node's subsystems as Deployments
# through the cluster API (with its pod's service account) and passes every job to one of them as a
# request over the cluster's broker; it runs no job itself. It needs no Docker CLI and no Docker socket.
# The chart's worker node template runs it as the pod of its Deployment worker-node-<name>.
FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        ca-certificates \
        git \
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
