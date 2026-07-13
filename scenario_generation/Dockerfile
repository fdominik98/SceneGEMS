FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Dependency layer: rebuilds when requirements.txt changes.
COPY scenario_generation/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt \
    && pip uninstall -y opencv-python opencv-contrib-python \
    && pip install --no-cache-dir opencv-python-headless

# Application layer: fast rebuild when only src / assets change.
COPY backend/pyproject.toml backend/setup.py backend/README.md ./
COPY backend/src ./src
COPY backend/assets/runtime_assets/scenario_generation ./assets/runtime_assets/scenario_generation
RUN pip install --no-cache-dir --no-deps -e .

CMD ["python", "-m", "scenegems_tool.scenario_generation.scenario_generation_service_main"]
