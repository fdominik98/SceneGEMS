FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    gnupg \
    lsb-release \
    wget \
    && rm -rf /var/lib/apt/lists/*

RUN wget -O /usr/share/keyrings/pkgs-osrf-archive-keyring.gpg https://packages.osrfoundation.org/gazebo.gpg && \
    echo "deb [signed-by=/usr/share/keyrings/pkgs-osrf-archive-keyring.gpg] http://packages.osrfoundation.org/gazebo/ubuntu-stable noble main" \
    > /etc/apt/sources.list.d/gazebo-stable.list

RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 \
    python3-gz-msgs10 \
    python3-gz-transport13 \
    && rm -rf /var/lib/apt/lists/*

# Match Gazebo Harmonic image so gz-transport discovers the running sim on Docker networks.
ENV GZ_PARTITION=scenegems
ENV LC_NUMERIC=C
ENV PYTHONUNBUFFERED=1

WORKDIR /app
COPY ardupilot_gazebo.py /app/ardupilot_gazebo.py

CMD ["python3", "-u", "/app/ardupilot_gazebo.py"]
