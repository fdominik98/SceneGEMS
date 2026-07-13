#!/usr/bin/env bash

set -euo pipefail

GZ_HEADLESS="${GZ_HEADLESS:-1}"
GZ_VERBOSE="${GZ_VERBOSE:-4}"
DISPLAY_VALUE="${DISPLAY:-}"
MODELS_DIR="${MODELS_DIR:-/models}"

# Qt dark mode (Fusion + qt5ct)
export QT_STYLE_OVERRIDE=Fusion
export QT_QPA_PLATFORMTHEME=qt5ct

# --- Start Gazebo ---------------------------------------------------------

if [[ "${GZ_HEADLESS}" == "1" || "${GZ_HEADLESS}" == "true" || "${GZ_HEADLESS}" == "TRUE" ]]; then
    echo "Starting Gazebo Harmonic in headless server mode..."
    gz sim -s -r -v"${GZ_VERBOSE}" "${WORLD_SDF:-/worlds/ocean.sdf}" &
else
    # Git Bash on Windows can set DISPLAY to placeholders like "needs-to-be-defined".
    # In that case GUI fails hard, so keep runtime alive by falling back to headless.
    if [[ -z "${DISPLAY_VALUE}" || "${DISPLAY_VALUE}" == "needs-to-be-defined" ]]; then
        echo "GUI requested but DISPLAY is invalid ('${DISPLAY_VALUE:-<empty>}'); falling back to headless."
        gz sim -s -r -v"${GZ_VERBOSE}" "${WORLD_SDF:-/worlds/ocean.sdf}" &
    else
        echo "Starting Gazebo Harmonic with GUI (DISPLAY=${DISPLAY_VALUE})..."
        gz sim -r -v"${GZ_VERBOSE}" "${WORLD_SDF:-/worlds/ocean.sdf}" &
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

wait "${GZ_PID}"

# # --- Vessel spawning ------------------------------------------------------

# if [[ ! -d "${MODELS_DIR}" ]]; then
#     echo "Models directory not found at ${MODELS_DIR}" >&2
#     kill "${GZ_PID}" >/dev/null 2>&1 || true
#     exit 1
# fi

# spawn_vessel() {
#     local vessel_model_file="$1"
#     local agent_name="$2"

#     echo "Attempting to spawn ${agent_name} from ${vessel_model_file}..."

#     # We use a Z-height of 0.2 to 0.3.
#     # This places the center of the hull slightly above the water
#     # to avoid a massive displacement calculation on the first frame.
#     local attempt=1
#     local max_attempts=5
#     local response=""

#     while [[ ${attempt} -le ${max_attempts} ]]; do
#         # Use the service call to create the entity
#         response="$(
#             gz service -s /world/ocean_world/create \
#                 --reqtype gz.msgs.EntityFactory \
#                 --reptype gz.msgs.Boolean \
#                 --timeout 3000 \
#                 --req "sdf_filename: \"${vessel_model_file}\" name: \"${agent_name}\"" 2>&1 || true
#         )"

#         if [[ "${response}" == *"data: true"* ]]; then
#             echo "Spawn succeeded for ${agent_name}."
#             # Crucial: sleep briefly to let physics settle
#             sleep 2
#             return 0
#         fi

#         echo "Spawn attempt ${attempt} failed for ${agent_name}: ${response}"
#         sleep 2
#         attempt=$((attempt + 1))
#     done

#     echo "ERROR: Failed to spawn ${agent_name} from ${vessel_model_file}."
#     return 1
# }

# echo "Spawning configured vessels..."

# shopt -s nullglob
# vessel_model_files=("${MODELS_DIR}"/*_model.sdf)

# if [[ ${#vessel_model_files[@]} -eq 0 ]]; then
#     echo "ERROR: No SDF model files found in ${MODELS_DIR}." >&2
#     kill "${GZ_PID}" >/dev/null 2>&1 || true
#     exit 1
# fi

# for vessel_model_file in "${vessel_model_files[@]}"; do
#     model_filename="$(basename "${vessel_model_file}")"
#     agent_name="${model_filename%.sdf}"
#     agent_name="${agent_name%_model}"

#     echo "Spawning ${agent_name}..."
#     spawn_vessel "${vessel_model_file}" "${agent_name}"
# done

# echo "All vessels spawned."
# echo "Current Models:"
# gz model --list || true

# # --- Hand control back to Gazebo -----------------------------------------

# wait "${GZ_PID}"
