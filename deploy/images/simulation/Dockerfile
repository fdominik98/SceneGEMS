# scenegems-simulation-subsystem: the simulation subsystem's service and the runner of a run.
#
# The same image runs as two things. As the worker node's long-lived simulation subsystem (the default command) it
# takes run-simulation requests from the broker and creates each run's pod through the cluster API, with the
# service account of its pod; it needs no Docker. As the runner container of a run's pod it is given the job
# container main as its command and owns the run's clock.
FROM python:3.12-slim

WORKDIR /app

# CA certificates for a broker with TLS (a run with a real vessel on an external broker)
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        ca-certificates \
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
