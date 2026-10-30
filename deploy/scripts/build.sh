#!/usr/bin/env bash
set -euo pipefail

source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/docker-common.sh"
docker_common_init

BUILD_BACKEND=0
BUILD_FRONTEND=0
BUILD_SIMULATION=0
BUILD_ARDUAGENT=0
BUILD_NODE=0
BUILD_ALL=0
BUILD_BROKER=0
BUILD_NO_CHECK=0
RELEASE_DIR=""
# Images the release bundle needs that SceneGEMS does not build (cluster/release/roles.py)
RELEASE_PULLED_IMAGES=("postgres:16.10-alpine")

print_build_help() {
    cat <<'EOF'
Usage: ./build.sh [OPTIONS]

Build SceneGEMS Docker images (stale-aware; only rebuilds when inputs change).

With no options, builds every image in the project.

Options:
  -h, --help              Show this help and exit

  -1, --backend           scenegems-backend and Python subsystems (monitor,
                          scene-generation, trajectory-generation,
                          scenario-execution)

  -2, --frontend          Frontend only (scenegems-frontend:dev)

  -3, --stack             Main application stack: same as -1 and -2 together
                          (backend + subsystems + frontend; no simulation images)

  -4, --arduagent         ArduPilot agent only (scenegems-arduagent:latest)

  -5, --node              Node daemon image only (scenegems-node:latest); a worker
                          also needs the subsystem images its capabilities run

  --simulation            Simulation runtime images only: Gazebo, SITL, MAVProxy
                          (scenegems-gazebo-harmonic, scenegems-ardupilot-sitl, scenegems-mavproxy)

  --all                   Build every image (same as no arguments)

  --release <folder>      Build the images a cluster runs (broker, backend and
                          subsystems, simulation, node daemon) as :latest, pull
                          Postgres, tag the release's images with the revision
                          (<commit>, or <commit>-dirty with uncommitted changes)
                          and write the release bundle into <folder>: release.json
                          with those tags, and the master and node stacks. The
                          deployment tool installs the bundle on the machines.

  --fingerprints          Print "image fingerprint" for every image of this checkout
                          and exit; builds nothing and needs no Docker engine

  --no-check              Skip stale/fingerprint checks; always run docker build
                          for the selected images (stamps updated after build).
                          With no other options, builds every image (same as
                          ./build.sh --all --no-check). Full builds run the
                          application stack (broker, backend, frontend) before
                          simulation images.

Examples:
  ./build.sh                      # full build
  ./build.sh --backend              # after Python/backend changes
  ./build.sh --frontend             # after UI changes
  ./build.sh --stack                # backend + frontend, skip simulation
  ./build.sh --arduagent            # agent image only
  ./build.sh --release ../release   # images and bundle for the deployment tool
  ./build.sh --backend --simulation # backend stack + simulation images
  ./build.sh --backend --no-check   # force rebuild backend images
EOF
}

parse_build_args() {
    if [ "$#" -eq 0 ]; then
        BUILD_ALL=1
        return
    fi

    while [ "$#" -gt 0 ]; do
        case "$1" in
            -h | --help)
                print_build_help
                exit 0
                ;;
            -1 | --backend | --subsystems)
                BUILD_BACKEND=1
                ;;
            -2 | --frontend)
                BUILD_FRONTEND=1
                ;;
            -3 | --stack | --app)
                BUILD_BACKEND=1
                BUILD_FRONTEND=1
                ;;
            -4 | --arduagent)
                BUILD_ARDUAGENT=1
                ;;
            -5 | --node)
                BUILD_NODE=1
                ;;
            --simulation)
                BUILD_SIMULATION=1
                ;;
            --all)
                BUILD_ALL=1
                ;;
            --no-check)
                BUILD_NO_CHECK=1
                ;;
            --release)
                shift
                RELEASE_DIR="${1:-}"
                if [ -z "$RELEASE_DIR" ]; then
                    echo "--release needs a folder" >&2
                    exit 1
                fi
                ;;
            --fingerprints)
                export DOCKER_FINGERPRINT_ONLY=1
                BUILD_ALL=1
                ;;
            *)
                echo "Unknown option: $1" >&2
                echo "Run ./build.sh --help for usage." >&2
                exit 1
                ;;
        esac
        shift
    done
}

build_simulation_images() {
    [ "${DOCKER_FINGERPRINT_ONLY:-0}" = "1" ] || echo "== Simulation images =="
    # Gazebo and SITL declare the upstream pins of deploy/images/upstream_pins.env as build
    # arguments, so the helpers pass them and add the pins file to both fingerprints.
    build_subsystem_if_stale "scenegems-gazebo-harmonic:latest" "$SCRIPT_DIR/deploy/images/gazebo/Dockerfile" \
        "$SCRIPT_DIR/deploy/images/gazebo" \
        "$SCRIPT_DIR/backend/src/scenegems_tool/vessel_stack/simulation_layers/gazebo/gz_transport_actuator.py"
    build_subsystem_if_stale "scenegems-ardupilot-sitl:latest" "$SCRIPT_DIR/deploy/images/sitl/Dockerfile" \
        "$SCRIPT_DIR/deploy/images/sitl/Dockerfile" "$SCRIPT_DIR/deploy/images/sitl" "$SCRIPT_DIR/deploy/images/gazebo/sitl_entrypoint.sh"
    build_if_stale "scenegems-mavproxy:latest" "$SCRIPT_DIR/deploy/images/mavproxy/Dockerfile" "$SCRIPT_DIR/deploy/images/mavproxy"
}

build_arduagent_image() {
    [ "${DOCKER_FINGERPRINT_ONLY:-0}" = "1" ] || echo "== Arduagent =="
    build_if_stale "scenegems-arduagent:latest" "$SCRIPT_DIR/deploy/images/arduagent/Dockerfile" "$SCRIPT_DIR/deploy/images/arduagent"
}

build_broker_image() {
    [ "${DOCKER_FINGERPRINT_ONLY:-0}" = "1" ] || echo "== MQTT broker =="
    build_if_stale "scenegems-mqtt-broker:latest" "$SCRIPT_DIR/deploy/images/mqtt_broker/Dockerfiles/nanomq/Dockerfile" "$SCRIPT_DIR/deploy/images/mqtt_broker/Dockerfiles/nanomq"
}

build_backend_stack_images() {
    [ "${DOCKER_FINGERPRINT_ONLY:-0}" = "1" ] || echo "== Backend stack =="
    build_subsystem_if_stale "scenegems-monitoring-subsystem:latest" "$SCRIPT_DIR/deploy/images/monitoring/Dockerfile" \
        "$SCRIPT_DIR/deploy/images/monitoring/requirements.txt" "$SCRIPT_DIR/deploy/images/monitoring/Dockerfile" \
        "$SCRIPT_DIR/backend/pyproject.toml" "$SCRIPT_DIR/backend/setup.py" "$SCRIPT_DIR/backend/README.md" "$SCRIPT_DIR/backend/src" \
        "$SCRIPT_DIR/backend/assets/domain_config"
    build_subsystem_if_stale "scenegems-scenario-execution-subsystem:latest" "$SCRIPT_DIR/deploy/images/scenario_execution/Dockerfile" \
        "$SCRIPT_DIR/deploy/images/scenario_execution/requirements.txt" "$SCRIPT_DIR/deploy/images/scenario_execution/Dockerfile" \
        "$SCRIPT_DIR/backend/pyproject.toml" "$SCRIPT_DIR/backend/setup.py" "$SCRIPT_DIR/backend/README.md" "$SCRIPT_DIR/backend/src" \
        "$SCRIPT_DIR/backend/assets/domain_config"
    build_subsystem_if_stale "scenegems-scene-generation-subsystem:latest" "$SCRIPT_DIR/deploy/images/scene_generation/Dockerfile" \
        "$SCRIPT_DIR/deploy/images/scene_generation/requirements.txt" "$SCRIPT_DIR/deploy/images/scene_generation/Dockerfile" \
        "$SCRIPT_DIR/backend/pyproject.toml" "$SCRIPT_DIR/backend/setup.py" "$SCRIPT_DIR/backend/README.md" "$SCRIPT_DIR/backend/src" \
        "$SCRIPT_DIR/backend/assets/runtime_assets/scene_generation"
    build_subsystem_if_stale "scenegems-trajectory-generation-subsystem:latest" "$SCRIPT_DIR/deploy/images/trajectory_generation/Dockerfile" \
        "$SCRIPT_DIR/deploy/images/trajectory_generation/requirements.txt" "$SCRIPT_DIR/deploy/images/trajectory_generation/Dockerfile" \
        "$SCRIPT_DIR/backend/pyproject.toml" "$SCRIPT_DIR/backend/setup.py" "$SCRIPT_DIR/backend/README.md" "$SCRIPT_DIR/backend/src" \
        "$SCRIPT_DIR/backend/assets/domain_config"
    build_subsystem_if_stale "scenegems-backend:latest" "$SCRIPT_DIR/backend/Dockerfile" \
        "$SCRIPT_DIR/backend/Dockerfile" "$SCRIPT_DIR/backend/pyproject.toml" "$SCRIPT_DIR/backend/setup.py" \
        "$SCRIPT_DIR/backend/README.md" "$SCRIPT_DIR/backend/src" "$SCRIPT_DIR/backend/assets"
}

build_node_image() {
    [ "${DOCKER_FINGERPRINT_ONLY:-0}" = "1" ] || echo "== Node daemon =="
    build_subsystem_if_stale "scenegems-node:latest" "$SCRIPT_DIR/deploy/images/node/Dockerfile"         "$SCRIPT_DIR/deploy/images/node/requirements.txt" "$SCRIPT_DIR/deploy/images/node/Dockerfile"         "$SCRIPT_DIR/backend/pyproject.toml" "$SCRIPT_DIR/backend/setup.py" "$SCRIPT_DIR/backend/README.md" "$SCRIPT_DIR/backend/src"         "$SCRIPT_DIR/backend/assets/domain_config" "$SCRIPT_DIR/backend/assets/runtime_assets"
}

build_frontend_image() {
    [ "${DOCKER_FINGERPRINT_ONLY:-0}" = "1" ] || echo "== Frontend =="
    build_if_stale "scenegems-frontend:dev" "$SCRIPT_DIR/frontend/Dockerfile" "$SCRIPT_DIR/frontend"
}

parse_build_args "$@"

# A release builds what a cluster runs; the frontend and ArduAgent belong to the workbench.
if [ -n "$RELEASE_DIR" ]; then
    BUILD_BROKER=1
    BUILD_BACKEND=1
    BUILD_SIMULATION=1
    BUILD_NODE=1
fi

# Modifier-only invocations (e.g. ./build.sh --no-check) should build everything,
# same as running ./build.sh with no arguments.
if [ "$BUILD_ALL" -eq 0 ] && [ "$BUILD_BACKEND" -eq 0 ] && [ "$BUILD_FRONTEND" -eq 0 ] \
    && [ "$BUILD_SIMULATION" -eq 0 ] && [ "$BUILD_ARDUAGENT" -eq 0 ] && [ "$BUILD_NODE" -eq 0 ]; then
    BUILD_ALL=1
fi

if [ "$BUILD_NO_CHECK" -eq 1 ]; then
    export DOCKER_BUILD_SKIP_CHECK=1
fi

if [ "$BUILD_ALL" -eq 1 ]; then
    BUILD_BROKER=1
    BUILD_BACKEND=1
    BUILD_FRONTEND=1
    BUILD_SIMULATION=1
    BUILD_ARDUAGENT=1
    BUILD_NODE=1
fi

print_selected_build_targets() {
    local targets=()
    if [ "$BUILD_BROKER" -eq 1 ]; then
        targets+=("mqtt-broker")
    fi
    if [ "$BUILD_BACKEND" -eq 1 ]; then
        targets+=("backend-stack")
    fi
    if [ "$BUILD_FRONTEND" -eq 1 ]; then
        targets+=("frontend")
    fi
    if [ "$BUILD_SIMULATION" -eq 1 ]; then
        targets+=("simulation")
    fi
    if [ "$BUILD_ARDUAGENT" -eq 1 ]; then
        targets+=("arduagent")
    fi
    if [ "$BUILD_NODE" -eq 1 ]; then
        targets+=("node")
    fi
    if [ "${#targets[@]}" -eq 0 ]; then
        echo "No build targets selected." >&2
        exit 1
    fi
    local mode="stale-aware"
    if [ "$BUILD_NO_CHECK" -eq 1 ]; then
        mode="force rebuild (--no-check)"
    fi
    echo "SceneGEMS image build ($mode): ${targets[*]}"
    echo ""
}

if [ "${DOCKER_FINGERPRINT_ONLY:-0}" != "1" ]; then
    print_selected_build_targets
fi

# Application stack first (broker, backend, frontend), then optional simulation images.
if [ "$BUILD_BROKER" -eq 1 ]; then
    build_broker_image
fi
if [ "$BUILD_BACKEND" -eq 1 ]; then
    build_backend_stack_images
fi
if [ "$BUILD_FRONTEND" -eq 1 ]; then
    build_frontend_image
fi
if [ "$BUILD_SIMULATION" -eq 1 ]; then
    build_simulation_images
fi
if [ "$BUILD_ARDUAGENT" -eq 1 ]; then
    build_arduagent_image
fi
if [ "$BUILD_NODE" -eq 1 ]; then
    build_node_image
fi

if [ "${DOCKER_FINGERPRINT_ONLY:-0}" = "1" ]; then
    exit 0
fi

# The Python of the backend's virtual environment, else the one on the PATH.
release_python() {
    local candidate
    for candidate in "$SCRIPT_DIR/backend/env/Scripts/python.exe" "$SCRIPT_DIR/backend/env/bin/python"; do
        if [ -x "$candidate" ]; then
            echo "$candidate"
            return
        fi
    done
    command -v python3 || command -v python
}

if [ -n "$RELEASE_DIR" ]; then
    for image in "${RELEASE_PULLED_IMAGES[@]}"; do
        image_exists "$image" || docker pull "$image"
    done
    echo ""
    echo "== Release bundle =="
    PYTHONPATH="$SCRIPT_DIR/backend/src" "$(release_python)" -m scenegems_tool.cluster.release --out "$RELEASE_DIR"
    exit 0
fi

if [ "$BUILD_BACKEND" -eq 1 ] || [ "$BUILD_FRONTEND" -eq 1 ] || [ "$BUILD_ALL" -eq 1 ]; then
    ensure_compose_volumes
fi

echo ""
if [ "$BUILD_ALL" -eq 1 ]; then
    echo "All SceneGEMS images are ready. Run ./start.sh to start the stack."
elif [ "$BUILD_BACKEND" -eq 1 ] && [ "$BUILD_FRONTEND" -eq 1 ] && [ "$BUILD_SIMULATION" -eq 0 ] && [ "$BUILD_ARDUAGENT" -eq 0 ]; then
    echo "Application stack images are ready. Run ./start.sh to start the stack."
else
    echo "Selected images are ready."
fi
