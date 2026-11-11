# syntax=docker/dockerfile:1
# Design space exploration subsystem: the Refinery fork's scenegems module, built from the
# pinned commit of deploy/images/upstream_pins.env (the same build and test stages as its
# scenegems/docker/Dockerfile, but the source is fetched instead of copied from the build context),
# and the subsystem's request service around it. The Gradle build does not read the git metadata, so
# the fetched folder is built as it is. The build context is the repository root: the runtime stage
# copies the service's requirements and backend/src from it.
ARG TEMURIN_JDK_IMAGE
ARG TEMURIN_JRE_IMAGE

FROM ${TEMURIN_JDK_IMAGE} AS build
ARG TARGETARCH
ARG REFINERY_REPO
ARG REFINERY_COMMIT
RUN apt-get update && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /refinery
RUN : "${REFINERY_REPO:?missing build arg, see deploy/images/upstream_pins.env}" && \
    : "${REFINERY_COMMIT:?missing build arg, see deploy/images/upstream_pins.env}" && \
    git init -q && \
    git remote add origin "$REFINERY_REPO" && \
    git fetch -q --depth 1 origin "$REFINERY_COMMIT" && \
    git checkout -q FETCH_HEAD && \
    test "$(git rev-parse HEAD)" = "$REFINERY_COMMIT"
RUN --mount=type=cache,target=/root/.gradle \
    ./gradlew --no-daemon --console=plain :refinery-scenegems:distTar
# Keep only the native solver jars of the target platform; the start script skips the missing ones.
RUN set -eux; \
    mkdir /dist; \
    tar -xf scenegems/build/distributions/refinery-scenegems-*.tar -C /dist --strip-components=1; \
    rm -f /dist/lib/*-darwin-*.jar /dist/lib/*-win32-*.jar; \
    case "${TARGETARCH:-amd64}" in \
      amd64) rm -f /dist/lib/*-linux-aarch64-*.jar ;; \
      arm64) rm -f /dist/lib/*-linux-x86-64-*.jar ;; \
    esac

FROM build AS test
RUN --mount=type=cache,target=/root/.gradle \
    ./gradlew --no-daemon --console=plain :refinery-scenegems:test

# The runtime keeps the generator's base and adds the subsystem's service next to it: Python in a virtual
# environment and the backend source. The service takes explore-design-space requests from the broker and
# runs the generator as a child process per task (scenegems_tool/subsystems/design_space_exploration).
FROM ${TEMURIN_JRE_IMAGE} AS runtime
ARG TEMURIN_JDK_IMAGE
ARG TEMURIN_JRE_IMAGE
ARG REFINERY_COMMIT
RUN apt-get update && apt-get install -y --no-install-recommends python3 python3-venv \
    && rm -rf /var/lib/apt/lists/* \
    && python3 -m venv /opt/venv
ENV PATH="/opt/venv/bin:${PATH}"

# Dependency layer: rebuilds when requirements.txt changes.
COPY deploy/images/design_space_exploration/requirements.txt /service/requirements.txt
RUN pip install --no-cache-dir -r /service/requirements.txt

COPY --link --from=build /dist /app
RUN ln -s /app/bin/refinery-scenegems /usr/local/bin/generate-models \
    && mkdir /job && chown 1000:1000 /job

# Application layer: fast rebuild when only src changes. The service runs as user 1000 and makes its folders below /service.
WORKDIR /service
COPY backend/pyproject.toml backend/setup.py backend/README.md ./
COPY backend/src ./src
RUN pip install --no-cache-dir --no-deps -e . \
    && mkdir -p /service/assets && chown -R 1000:1000 /service

# The service gives each generator its share of the heap (JAVA_OPTS per task); this is the share of a generator started by hand.
ENV JAVA_OPTS="-XX:MaxRAMPercentage=75" \
    PYTHONPATH=/service/src \
    PYTHONUNBUFFERED=1
LABEL org.scenegems.base_image="${TEMURIN_JRE_IMAGE}" \
      org.scenegems.build_image="${TEMURIN_JDK_IMAGE}" \
      org.scenegems.upstream.refinery="${REFINERY_COMMIT}"
USER 1000
CMD ["python", "-m", "scenegems_tool.subsystems.design_space_exploration.design_space_exploration_service_main"]
