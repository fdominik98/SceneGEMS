FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY scenario_execution/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/pyproject.toml backend/setup.py backend/README.md ./
COPY backend/src ./src
COPY backend/assets/domain_config ./assets/domain_config
RUN pip install --no-cache-dir --no-deps -e .

CMD ["python", "-m", "scenegems_tool.simulators.scenario_execution_service_main"]
