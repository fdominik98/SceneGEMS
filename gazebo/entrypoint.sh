#!/usr/bin/env bash

set -euo pipefail

GZ_HEADLESS="${GZ_HEADLESS:-1}"
GZ_VERBOSE="${GZ_VERBOSE:-4}"
DISPLAY_VALUE="${DISPLAY:-}"

# Spawn this SDF as-is (no copy/substitution). Path must exist inside the container.
MODEL_SDF="${MODEL_SDF:-/models/model.sdf}"
# MODEL_SDF="${MODEL_SDF:-/models/model.sdf}"

# Qt dark mode (Fusion + qt5ct)
export QT_STYLE_OVERRIDE=Fusion
export QT_QPA_PLATFORMTHEME=qt5ct

# --- Start Gazebo ---------------------------------------------------------

if [[ "${GZ_HEADLESS}" == "1" || "${GZ_HEADLESS}" == "true" || "${GZ_HEADLESS}" == "TRUE" ]]; then
    echo "Starting Gazebo Harmonic in headless server mode..."
    gz sim -s -r -v"${GZ_VERBOSE}" /worlds/ocean.sdf &
else
    # Git Bash on Windows can set DISPLAY to placeholders like "needs-to-be-defined".
    # In that case GUI fails hard, so keep runtime alive by falling back to headless.
    if [[ -z "${DISPLAY_VALUE}" || "${DISPLAY_VALUE}" == "needs-to-be-defined" ]]; then
        echo "GUI requested but DISPLAY is invalid ('${DISPLAY_VALUE:-<empty>}'); falling back to headless."
        gz sim -s -r -v"${GZ_VERBOSE}" /worlds/ocean.sdf &
    else
        echo "Starting Gazebo Harmonic with GUI (DISPLAY=${DISPLAY_VALUE})..."
        gz sim -r -v"${GZ_VERBOSE}" /worlds/ocean.sdf | grep ArduPilot &
    fi
fi

GZ_PID=$!

# Gate spawning on the actual service we're about to call. Polling `gz topic -l`
# only proves the transport layer is alive (the GUI publishes topics very early)
# and therefore returns success long before the server has finished loading
# `ocean_world` and advertising `/world/ocean_world/create`. Spawning that early
# yields "Service call timed out" failures even though Gazebo eventually comes up.
SPAWN_SERVICE="/world/ocean_world/create"
SPAWN_READY_TIMEOUT="${SPAWN_READY_TIMEOUT:-90}"

echo "Waiting up to ${SPAWN_READY_TIMEOUT}s for ${SPAWN_SERVICE} to be advertised..."
spawn_ready=0
for _ in $(seq 1 "${SPAWN_READY_TIMEOUT}"); do
    if gz service -l 2>/dev/null | grep -Fxq "${SPAWN_SERVICE}"; then
        spawn_ready=1
        break
    fi
    sleep 1
done

if [[ "${spawn_ready}" -ne 1 ]]; then
    echo "ERROR: ${SPAWN_SERVICE} not advertised after ${SPAWN_READY_TIMEOUT}s; aborting." >&2
    kill "${GZ_PID}" >/dev/null 2>&1 || true
    exit 1
fi
echo "Gazebo world is ready; ${SPAWN_SERVICE} is advertised."

# --- Vessel spawning ------------------------------------------------------

if [[ ! -f "${MODEL_SDF}" ]]; then
    echo "Vessel model SDF not found at ${MODEL_SDF}" >&2
    exit 1
fi

# Root model name in the SDF must match the spawn name so plugin topics like
# /model/<name>/joint/... stay consistent with the file (spawn does not rewrite URIs in plugins).
spawn_model_name="$(sed -n 's/.*<model name="\([^"]*\)".*/\1/p' "${MODEL_SDF}" | head -n1)"
if [[ -z "${spawn_model_name}" ]]; then
    echo "ERROR: Could not parse <model name=\"...\"> from ${MODEL_SDF}" >&2
    exit 1
fi

spawn_vessel_from_sdf() {
    local sdf_path="$1"
    local entity_name="$2"

    echo "Attempting to spawn entity \"${entity_name}\" from ${sdf_path}..."

    local attempt=1
    local max_attempts=5
    local response=""

    while [[ ${attempt} -le ${max_attempts} ]]; do
        response="$(
            gz service -s /world/ocean_world/create \
                --reqtype gz.msgs.EntityFactory \
                --reptype gz.msgs.Boolean \
                --timeout 3000 \
                --req "sdf_filename: \"${sdf_path}\" name: \"${entity_name}\"" 2>&1 || true
        )"

        if [[ "${response}" == *"data: true"* ]]; then
            echo "Spawn succeeded for ${entity_name}."
            sleep 2
            return 0
        fi

        echo "Spawn attempt ${attempt} failed: ${response}"
        sleep 2
        attempt=$((attempt + 1))
    done

    echo "ERROR: Failed to spawn ${entity_name} from ${sdf_path}." >&2
    return 1
}

echo "Spawning configured vessels..."

sleep 5

echo "Spawning ${spawn_model_name}..."
spawn_vessel_from_sdf "${MODEL_SDF}" "${spawn_model_name}"

echo "All vessels spawned."
echo "Current Models:"
gz model --list || true

# --- Hand control back to Gazebo -----------------------------------------

wait "${GZ_PID}"
