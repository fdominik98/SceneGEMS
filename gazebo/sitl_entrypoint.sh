#!/usr/bin/env bash
# ArduPilot SITL launcher for Gazebo JSON physics.
# Env vars (defaults match docker-compose-gazebo.yml sitl1):
#   SITL_RESOLVE_HOST   Docker DNS name for the Gazebo service (default: gazebo)
#   SITL_SIM_ADDRESS      If set, used as --sim-address directly (skip DNS resolve; IPv4)
#   SITL_VEHICLE          -v argument (default: Rover)
#   SITL_FRAME            -f frame (default: rover-skid)
#   SITL_PARAM_FILE       --add-param-file path (default: /params/gazebo_boat_motors.parm)
#   SITL_SIMULATOR        gazebo | ardupilot (default: gazebo). ardupilot = internal SITL physics, no Gazebo FDM.
#   SITL_MODEL            --model when SITL_SIMULATOR=gazebo (default: JSON)
#   SITL_NO_MAVPROXY      Set to 0 to omit --no-mavproxy (default: 1)
#   SITL_NO_REBUILD       Set to 0 to omit --no-rebuild (default: 1)
#   SITL_SPEEDUP          Optional --speedup value
#   SITL_INSTANCE         Optional --instance
#   SITL_SYSID            Optional --sysid
#   SITL_CUSTOM_LOCATION  Optional --custom-location=lat,lon,alt,yaw

set -euo pipefail

: "${SITL_SIMULATOR:=gazebo}"
: "${SITL_RESOLVE_HOST:=gazebo}"
: "${SITL_VEHICLE:=Rover}"
: "${SITL_FRAME:=rover-skid}"
: "${SITL_PARAM_FILE:=/params/gazebo_boat_motors.parm}"
: "${SITL_MODEL:=JSON}"
: "${SITL_NO_MAVPROXY:=1}"
: "${SITL_NO_REBUILD:=1}"

_resolve_ipv4() {
    local host="$1"
    local ip=""
    ip="$(getent ahostsv4 "$host" 2>/dev/null | awk '/STREAM/ { print $1; exit }' || true)"
    if [[ -z "$ip" ]]; then
        ip="$(getent hosts "$host" 2>/dev/null | head -1 | awk '{ print $1 }' || true)"
    fi
    printf '%s' "$ip"
}

cmd=(sim_vehicle.py -v "$SITL_VEHICLE" -f "$SITL_FRAME")
if [[ "${SITL_NO_MAVPROXY}" == "1" ]]; then
    cmd+=(--no-mavproxy)
fi
if [[ "${SITL_NO_REBUILD}" == "1" ]]; then
    cmd+=(--no-rebuild)
fi
cmd+=(--add-param-file="$SITL_PARAM_FILE")

if [[ "${SITL_SIMULATOR}" == "gazebo" ]]; then
    if [[ -n "${SITL_SIM_ADDRESS:-}" ]]; then
        simip="$SITL_SIM_ADDRESS"
    else
        simip="$(_resolve_ipv4 "$SITL_RESOLVE_HOST")"
    fi

    if [[ -z "$simip" ]]; then
        echo "sitl_entrypoint: could not resolve ${SITL_RESOLVE_HOST} to an address (set SITL_SIM_ADDRESS to override)" >&2
        exit 1
    fi

    echo "sitl_entrypoint: JSON FDM target ${simip} (${SITL_RESOLVE_HOST}; ArduPilotPlugin UDP/JSON)"
    cmd+=(--model "$SITL_MODEL" --sim-address "$simip")
else
    echo "sitl_entrypoint: internal ArduPilot SITL (no Gazebo FDM)"
fi

if [[ -n "${SITL_SPEEDUP:-}" ]]; then
    cmd+=(--speedup "$SITL_SPEEDUP")
fi
if [[ -n "${SITL_INSTANCE:-}" ]]; then
    cmd+=(--instance "$SITL_INSTANCE")
fi
if [[ -n "${SITL_SYSID:-}" ]]; then
    cmd+=(--sysid "$SITL_SYSID")
fi
if [[ -n "${SITL_CUSTOM_LOCATION:-}" ]]; then
    cmd+=(--custom-location="$SITL_CUSTOM_LOCATION")
fi

exec "${cmd[@]}"
