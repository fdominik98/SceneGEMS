# Upstream pins come from deploy/images/upstream_pins.env (passed by deploy/scripts/build.sh).
ARG UBUNTU_BASE_IMAGE
FROM ${UBUNTU_BASE_IMAGE}

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    ccache \
    clang \
    g++ \
    gawk \
    genromfs \
    git \
    libtool \
    libxml2-dev \
    libxslt1-dev \
    make \
    pkg-config \
    python3 \
    python3-dev \
    python3-pip \
    python3-venv \
    rsync \
    zlib1g-dev \
    tcpdump  \
    net-tools \
    && rm -rf /var/lib/apt/lists/*

# ArduPilot at the pinned commit; submodules follow the commit's gitlinks.
ARG ARDUPILOT_REPO
ARG ARDUPILOT_COMMIT
WORKDIR /opt/ardupilot
RUN : "${ARDUPILOT_REPO:?missing build arg, see deploy/images/upstream_pins.env}" && \
    : "${ARDUPILOT_COMMIT:?missing build arg, see deploy/images/upstream_pins.env}" && \
    git init -q && \
    git remote add origin "$ARDUPILOT_REPO" && \
    git fetch -q --depth 1 origin "$ARDUPILOT_COMMIT" && \
    git checkout -q FETCH_HEAD && \
    test "$(git rev-parse HEAD)" = "$ARDUPILOT_COMMIT"
RUN git submodule update --init --recursive

RUN python3 -m venv /opt/venv
ENV PATH="/opt/venv/bin:/opt/ardupilot/Tools/autotest:${PATH}"
ENV LC_NUMERIC=C

RUN pip install --upgrade pip==26.2.2 setuptools==84.2.1 wheel==0.48.0 && \
    pip install future==1.0.0 lxml==6.1.3 pymavlink==2.4.50 MAVProxy==1.8.75 pexpect==4.9.0 empy==4.2.1

# Build ArduRover SITL binary during image build so runtime starts fast.
RUN ./waf configure --board sitl && \
    ./waf rover

RUN apt-get update && apt-get install -y --no-install-recommends \
    iproute2 \
    iputils-ping \
    && rm -rf /var/lib/apt/lists/*

# apt and pip packages are not pinned: record the installed versions so a worker node can report them.
RUN mkdir -p /etc/scenegems/package_versions && \
    dpkg-query -W -f='${Package}=${Version}\n' | LC_ALL=C sort > /etc/scenegems/package_versions/dpkg.txt && \
    pip freeze --all | LC_ALL=C sort > /etc/scenegems/package_versions/pip.txt

WORKDIR /opt/ardupilot/ArduRover

COPY deploy/images/gazebo/sitl_entrypoint.sh /scripts/sitl_entrypoint.sh
RUN chmod +x /scripts/sitl_entrypoint.sh

ARG UBUNTU_BASE_IMAGE
LABEL org.scenegems.base_image="${UBUNTU_BASE_IMAGE}" \
      org.scenegems.upstream.ardupilot="${ARDUPILOT_COMMIT}" \
      org.scenegems.package_versions="/etc/scenegems/package_versions"

CMD ["bash"]
