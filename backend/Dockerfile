FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    ca-certificates \
    && curl -fsSL "https://download.docker.com/linux/static/stable/x86_64/docker-27.5.1.tgz" \
        | tar xz -C /usr/local/bin --strip-components=1 docker/docker \
    && curl -fsSL "https://github.com/docker/compose/releases/download/v2.32.4/docker-compose-linux-x86_64" \
        -o /usr/local/bin/docker-compose \
    && chmod +x /usr/local/bin/docker-compose \
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
    ./assets/runtime_assets/scenario_execution/gen_tmp \
    ./assets/runtime_assets/scenario_generation/gen_tmp
RUN pip install --no-cache-dir --no-deps -e .

ENV PYTHONPATH=/app/src

EXPOSE 8000

CMD ["uvicorn", "scenegems_tool.backend_service.websocket_app:app", "--host", "0.0.0.0", "--port", "8000"]
