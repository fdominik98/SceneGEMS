# USV Navigation as a plug and play ASV software component: colav_automaton behind the
# SceneGEMS lockstep wire protocol, one container per vessel. The image holds the component's
# server and the wire protocol it serves, at their module paths, and no other SceneGEMS code.
FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY deploy/images/usv_navigation/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/src/scenegems_tool/vessel_stack/contracts/lockstep_wire.py ./scenegems_tool/vessel_stack/contracts/lockstep_wire.py
COPY backend/src/scenegems_tool/vessel_stack/asv_software/usv_navigation/usv_navigation_server.py ./scenegems_tool/vessel_stack/asv_software/usv_navigation/usv_navigation_server.py

ENV PYTHONPATH=/app \
    PYTHONUNBUFFERED=1

CMD ["python", "-m", "scenegems_tool.vessel_stack.asv_software.usv_navigation.usv_navigation_server"]
