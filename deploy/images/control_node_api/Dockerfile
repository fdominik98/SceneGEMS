FROM python:3.12-slim

WORKDIR /app

# No Docker CLI: the control node starts no containers (every subsystem runs on a worker node)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY backend/pyproject.toml backend/setup.py backend/README.md ./
RUN python - <<'EOF'
import subprocess
import tomllib

with open("pyproject.toml", "rb") as file:
    dependencies = tomllib.load(file)["project"]["dependencies"]
subprocess.check_call(["pip", "install", "--no-cache-dir", *dependencies])
subprocess.run(
    ["pip", "uninstall", "-y", "opencv-python", "opencv-contrib-python"],
    stdout=subprocess.DEVNULL,
    stderr=subprocess.DEVNULL,
    check=False,
)
subprocess.check_call(["pip", "install", "--no-cache-dir", "opencv-python-headless"])
EOF

COPY backend/src ./src
COPY backend/assets ./assets
RUN rm -rf ./assets/runtime_assets/monitoring/gen_tmp \
    ./assets/runtime_assets/simulation/gen_tmp \
    ./assets/runtime_assets/scene_generation/gen_tmp
RUN pip install --no-cache-dir --no-deps -e .

ENV PYTHONPATH=/app/src

# Worker node API and the operator API with the workbench gateway (deploy/control_node/docker-compose.yml)
EXPOSE 8443 5174

CMD ["sh", "-c", "python -m scenegems_tool.persistence.migrate upgrade head && exec python -m scenegems_tool.cluster.control_node"]
