# MOOS-IvP as a plug and play ASV system component: pHelmIvP behind the SceneGEMS lockstep wire
# protocol, one container per vessel. The image holds MOOS-IvP's MOOSDB and pHelmIvP, the bridge
# client, the component's server and the wire protocol it serves, and no other SceneGEMS code.
#
# Upstream pins come from deploy/images/upstream_pins.env (passed by deploy/scripts/build.sh).
# MOOS_IVP_REPO is a fork of moos-ivp whose libMOOS can take its time from a clock the server
# steps (MOOS_EXTERNAL_CLOCK, MOOS_EXTERNAL_TICK), which is what makes a run repeatable.
ARG UBUNTU_BASE_IMAGE
FROM ${UBUNTU_BASE_IMAGE} AS build

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    ca-certificates \
    cmake \
    git \
    lsb-release \
    patch \
    && rm -rf /var/lib/apt/lists/*

# MOOS-IvP at the pinned commit.
ARG MOOS_IVP_REPO
ARG MOOS_IVP_COMMIT
WORKDIR /opt/moos-ivp
RUN : "${MOOS_IVP_REPO:?missing build arg, see deploy/images/upstream_pins.env}" && \
    : "${MOOS_IVP_COMMIT:?missing build arg, see deploy/images/upstream_pins.env}" && \
    git init -q && \
    git remote add origin "$MOOS_IVP_REPO" && \
    git fetch -q --depth 1 origin "$MOOS_IVP_COMMIT" && \
    git checkout -q FETCH_HEAD && \
    test "$(git rev-parse HEAD)" = "$MOOS_IVP_COMMIT"

# The MOOS core and, of the IvP tree, the helm alone (its behaviours are compiled into it).
# MOOSGeodesy downloads PROJ 5.2.0 during this build, as upstream's own build does.
RUN ./build-moos.sh --minrobot
RUN ./build-ivp.sh --minrobot pHelmIvP

COPY deploy/images/moos_ivp/bridge /opt/bridge
RUN cmake -S /opt/bridge -B /opt/bridge/build -DMOOS_DIR=/opt/moos-ivp/build/MOOS/MOOSCore -DCMAKE_BUILD_TYPE=Release && \
    cmake --build /opt/bridge/build

# What the component runs: three programs, and the one shared library the helm links.
RUN mkdir -p /opt/runtime/bin /opt/runtime/lib && \
    cp bin/MOOSDB bin/pHelmIvP /opt/bridge/build/scenegems_moos_bridge /opt/runtime/bin/ && \
    cp build/MOOS/MOOSGeodesy/lib/libMOOSGeodesy.so /opt/runtime/lib/


FROM ${UBUNTU_BASE_IMAGE}

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 \
    && rm -rf /var/lib/apt/lists/*

COPY --from=build /opt/runtime/bin/ /usr/local/bin/
COPY --from=build /opt/runtime/lib/ /usr/local/lib/
RUN ldconfig

WORKDIR /app
COPY backend/src/scenegems_tool/vessel_stack/contracts/lockstep_wire.py ./scenegems_tool/vessel_stack/contracts/lockstep_wire.py
COPY backend/src/scenegems_tool/vessel_stack/asv_system/moos_ivp/moos_ivp_server.py ./scenegems_tool/vessel_stack/asv_system/moos_ivp/moos_ivp_server.py

# apt packages are not pinned: record the installed versions so a worker node can report them.
RUN mkdir -p /etc/scenegems/package_versions && \
    dpkg-query -W -f='${Package}=${Version}\n' | LC_ALL=C sort > /etc/scenegems/package_versions/dpkg.txt

ARG UBUNTU_BASE_IMAGE
ARG MOOS_IVP_COMMIT
# The server reports the commit in every run record.
ENV PYTHONPATH=/app \
    PYTHONUNBUFFERED=1 \
    MOOS_IVP_COMMIT=${MOOS_IVP_COMMIT}
LABEL org.scenegems.base_image="${UBUNTU_BASE_IMAGE}" \
      org.scenegems.upstream.moos_ivp="${MOOS_IVP_COMMIT}" \
      org.scenegems.package_versions="/etc/scenegems/package_versions"

CMD ["python3", "-m", "scenegems_tool.vessel_stack.asv_system.moos_ivp.moos_ivp_server"]
