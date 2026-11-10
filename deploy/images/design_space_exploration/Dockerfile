# syntax=docker/dockerfile:1
# Design space exploration subsystem: the Refinery fork's scenegems module, built from the
# pinned commit of deploy/images/upstream_pins.env (the same stages as its scenegems/docker/Dockerfile,
# but the source is fetched instead of copied from the build context). The build context is not used;
# the Gradle build does not read the git metadata, so the fetched folder is built as it is.
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

FROM ${TEMURIN_JRE_IMAGE} AS runtime
ARG TEMURIN_JDK_IMAGE
ARG TEMURIN_JRE_IMAGE
ARG REFINERY_COMMIT
COPY --link --from=build /dist /app
RUN ln -s /app/bin/refinery-scenegems /usr/local/bin/generate-models \
    && mkdir /job && chown 1000:1000 /job
ENV JAVA_OPTS="-XX:MaxRAMPercentage=75"
LABEL org.scenegems.base_image="${TEMURIN_JRE_IMAGE}" \
      org.scenegems.build_image="${TEMURIN_JDK_IMAGE}" \
      org.scenegems.upstream.refinery="${REFINERY_COMMIT}"
USER 1000
WORKDIR /job
CMD ["generate-models", "job"]
