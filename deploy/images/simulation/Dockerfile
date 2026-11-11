FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY deploy/images/simulation/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/pyproject.toml backend/setup.py backend/README.md ./
COPY backend/src ./src
COPY backend/assets/domain_config ./assets/domain_config
RUN pip install --no-cache-dir --no-deps -e .

# Every job gives its own command; the default is the job runner (cluster/worker_node/launchers/per_job/job_container_io.py JOB_CONTAINER_MAIN)
CMD ["python", "-m", "scenegems_tool.cluster.worker_node.jobs.in_container.job_container_main"]
