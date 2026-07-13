FROM ubuntu:24.04

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

WORKDIR /opt
RUN git clone --depth 1 https://github.com/ArduPilot/ardupilot.git
WORKDIR /opt/ardupilot
RUN git submodule update --init --recursive

RUN python3 -m venv /opt/venv
ENV PATH="/opt/venv/bin:/opt/ardupilot/Tools/autotest:${PATH}"
ENV LC_NUMERIC=C

RUN pip install --upgrade pip setuptools wheel && \
    pip install future lxml pymavlink MAVProxy pexpect empy

# Build ArduRover SITL binary during image build so runtime starts fast.
RUN ./waf configure --board sitl && \
    ./waf rover

RUN apt-get update && apt-get install -y --no-install-recommends \
    iproute2 \
    iputils-ping \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /opt/ardupilot/ArduRover

COPY gazebo/sitl_entrypoint.sh /scripts/sitl_entrypoint.sh
RUN chmod +x /scripts/sitl_entrypoint.sh

CMD ["bash"]
