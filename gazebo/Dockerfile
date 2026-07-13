FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive

# 1. Install minimal tools to add the Gazebo repository
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    curl \
    gnupg \
    lsb-release \
    wget \
    && rm -rf /var/lib/apt/lists/*

# 2. Add the Gazebo Harmonic repository
RUN wget -O /usr/share/keyrings/pkgs-osrf-archive-keyring.gpg https://packages.osrfoundation.org/gazebo.gpg && \
    echo "deb [signed-by=/usr/share/keyrings/pkgs-osrf-archive-keyring.gpg] http://packages.osrfoundation.org/gazebo/ubuntu-stable noble main" \
    > /etc/apt/sources.list.d/gazebo-stable.list

# 3. Install Build Tools, OpenCV, ZeroMQ, RapidJSON, and Gazebo Headers
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    cmake \
    git \
    pkg-config \
    # ArduPilot plugin requirements
    libopencv-dev \
    rapidjson-dev \
    libgstreamer1.0-dev \
    libgstreamer-plugins-base1.0-dev \
    cppzmq-dev \
    libzmq3-dev \
    libgflags-dev \
    libprotobuf-dev \
    protobuf-compiler \
    # asv_wave_sim specific dependencies
    libcgal-dev \
    libfftw3-dev \
    libboost-all-dev \
    libboost-iostreams-dev \
    libboost-system-dev \
    # Gazebo Harmonic suite and dev headers
    gz-harmonic \
    libgz-sim8-dev \
    # gz-sim-waves-system (world plugin) lives in plugins, not pulled by gz-harmonic alone
    libgz-sim8-plugins \
    # srmainwaring/asv_sim (anemometer + wind systems) links sensors + sdformat14 on Harmonic
    libgz-sensors8-dev \
    libsdformat14-dev \
    libgz-common5-dev \
    libgz-math7-dev \
    libgz-msgs10-dev \
    libgz-plugin2-dev \
    libgz-transport13-dev \
    && rm -rf /var/lib/apt/lists/*

# 4. Build ArduPilot Gazebo Plugin
# Merge https://github.com/ArduPilot/ardupilot_gazebo/pull/166 before build (multi-instance
# ArduPilotPlugin: stable per-plugin FCU IP via inet_ntop; offline recovery duplicate-frame fix).
WORKDIR /opt
RUN git clone https://github.com/ArduPilot/ardupilot_gazebo.git && \
    cd ardupilot_gazebo && \
    git fetch origin pull/166/head:pr-166 && \
    git merge --no-edit pr-166 && \
    cmake -S . -B build -DCMAKE_BUILD_TYPE=RelWithDebInfo && \
    cmake --build build -j$(nproc) && \
    cmake --install build

# 5. ASV Sim2 system plugins (ocean.sdf: asv_sim2-anemometer-system, asv_sim2-wind-system)
# https://github.com/srmainwaring/asv_sim — build the Harmonic plugin stack (GZ_VERSION selects gz-sim8).
WORKDIR /opt
RUN git clone --depth 1 https://github.com/srmainwaring/asv_sim.git && \
    cd asv_sim/asv_sim_gazebo_plugins && \
    GZ_VERSION=harmonic cmake -S . -B build \
      -DCMAKE_BUILD_TYPE=RelWithDebInfo \
      -DCMAKE_INSTALL_PREFIX=/usr/local \
      -DBUILD_TESTING=OFF && \
    cmake --build build -j"$(nproc)" && \
    cmake --install build && \
    rm -rf /opt/asv_sim/.git

# 6. Environment Configuration
ENV GZ_VERSION=harmonic
ENV GZ_PARTITION=scenegems
ENV GZ_SIM_SYSTEM_PLUGIN_PATH=/usr/local/lib:/usr/local/lib/ardupilot_gazebo
ENV GZ_SIM_RESOURCE_PATH=/worlds:/models:/opt/asv_wave_sim/gz-waves-models/models
ENV LC_NUMERIC=C

COPY gazebo/models /models
COPY gazebo/gazebo_entrypoint_prod.sh /scripts/entrypoint.sh
RUN chmod +x /scripts/entrypoint.sh

WORKDIR /worlds
CMD ["bash"]