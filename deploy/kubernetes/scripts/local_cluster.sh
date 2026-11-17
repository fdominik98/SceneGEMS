#!/usr/bin/env bash
# A SceneGEMS cluster on this PC without Machine Hub: a k3d cluster in Docker, the release's images imported into it
# by tag, and the release's chart installed with local values (a control node and one worker node on the cluster's
# one node). The web console reaches the operator API through a port forward to the service control-node-api; the
# operator API is published on no host port.
#
#   ./build.sh --release ../release                                  # the images and the bundle (release.json, chart/)
#   deploy/kubernetes/scripts/local_cluster.sh up ../release         # create the cluster and install the release
#   deploy/kubernetes/scripts/local_cluster.sh forward               # the operator API on 127.0.0.1:5174 (until Ctrl+C)
#   deploy/kubernetes/scripts/local_cluster.sh status
#   deploy/kubernetes/scripts/local_cluster.sh down                  # delete the cluster with everything in it
#
# `up` on an existing cluster imports the images again and upgrades the release, so a new bundle is installed with
# `up` as well. The tests marked kubernetes create their clusters the same way (k3d_cluster.py, local_cluster.py).
#
# Settings (environment):
#   SCENEGEMS_LOCAL_CLUSTER     name of the k3d cluster and the cluster id (default scenegems-local); lowercase
#                               letters, digits and hyphens, at most 32 characters
#   SCENEGEMS_LOCAL_COMPONENTS  the worker node's components, comma separated (default: the worker node role's default
#                               of release.json, a kinematic worker node with every subsystem)
#   SCENEGEMS_LOCAL_SLOTS       its slots as type:n, comma separated (default: the role's default)
#   SCENEGEMS_LOCAL_NODE_PORTS  node ports mapped to 127.0.0.1, first-last (default 30100-30119): the API server
#                               assigns node ports from this range only, so an attended run's ground control port
#                               (Mission Planner) is reachable from this PC
#   SCENEGEMS_LOCAL_PORT        local port of `forward` (default 5174)
#   SCENEGEMS_LOCAL_STATE       folder of the kubeconfig and the values file (default ~/.scenegems/local/<cluster>)
#   SCENEGEMS_K3D, SCENEGEMS_HELM, SCENEGEMS_KUBECTL   the programs, else k3d, helm and kubectl on the PATH
#                               (k3d 5.9.0 and Helm 4.3.2 were used, the versions Machine Hub pins)
#
# Every kubectl and helm call names the cluster's kubeconfig: without one kubectl talks to 127.0.0.1:8080, which can
# be any program on this PC.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
CLUSTER="${SCENEGEMS_LOCAL_CLUSTER:-scenegems-local}"
NODE_PORTS="${SCENEGEMS_LOCAL_NODE_PORTS:-30100-30119}"
LOCAL_PORT="${SCENEGEMS_LOCAL_PORT:-5174}"
STATE="${SCENEGEMS_LOCAL_STATE:-$HOME/.scenegems/local/$CLUSTER}"
KUBECONFIG_FILE="$STATE/kubeconfig"
VALUES_FILE="$STATE/values.yaml"
START_TIMEOUT_S=300
WORKER_NODE="local"

usage() {
    sed -n '2,32p' "$0" | sed 's/^# \{0,1\}//'
    exit "${1:-0}"
}

fail() {
    echo "error: $*" >&2
    exit 1
}

program() {  # program <variable> <name>: the program a variable names, else the one on the PATH
    local named="${!1:-}"
    if [ -n "$named" ]; then
        [ -f "$named" ] || fail "$1=$named names no file"
        echo "$named"
        return
    fi
    command -v "$2" >/dev/null 2>&1 || command -v "$2.exe" >/dev/null 2>&1 || fail "$2 is needed: put it on the PATH or name it with $1"
    command -v "$2" 2>/dev/null || command -v "$2.exe"
}

# The Python of the backend's virtual environment, else the one on the PATH (as ./build.sh finds it); it only reads JSON.
release_python() {
    local candidate
    for candidate in "$REPO_ROOT/backend/env/Scripts/python.exe" "$REPO_ROOT/backend/env/bin/python"; do
        if [ -x "$candidate" ]; then
            echo "$candidate"
            return
        fi
    done
    command -v python3 || command -v python || fail "python is needed to read release.json"
}

tools() {
    K3D="$(program SCENEGEMS_K3D k3d)"
    HELM="$(program SCENEGEMS_HELM helm)"
    KUBECTL="$(program SCENEGEMS_KUBECTL kubectl)"
    command -v docker >/dev/null 2>&1 || fail "docker is needed (Docker Desktop on Windows)"
    [[ "$CLUSTER" =~ ^[a-z0-9]([-a-z0-9]{0,30}[a-z0-9])?$ ]] || fail "SCENEGEMS_LOCAL_CLUSTER=$CLUSTER: 1 to 32 lowercase letters, digits and hyphens"
    [[ "$NODE_PORTS" =~ ^[0-9]+-[0-9]+$ ]] || fail "SCENEGEMS_LOCAL_NODE_PORTS=$NODE_PORTS must read first-last"
}

kubectl_() { "$KUBECTL" --kubeconfig "$KUBECONFIG_FILE" "$@"; }
helm_() { "$HELM" --kubeconfig "$KUBECONFIG_FILE" "$@"; }

cluster_exists() {
    "$K3D" cluster list "$CLUSTER" >/dev/null 2>&1
}

free_port() {  # a free port on 127.0.0.1, for the cluster's API
    "$(release_python)" -I -c 'import socket; s = socket.socket(); s.bind(("127.0.0.1", 0)); print(s.getsockname()[1])'
}

create_cluster() {
    local arguments=(
        cluster create "$CLUSTER"
        --servers 1 --agents 0 --no-lb
        --api-port "127.0.0.1:$(free_port)"
        # The node ports, straight onto the server node (no load balancer), and the API server told to assign only
        # these, since only ports mapped now reach this PC
        --port "127.0.0.1:$NODE_PORTS:$NODE_PORTS@server:0:direct"
        --k3s-arg "--service-node-port-range=$NODE_PORTS@server:0"
        --k3s-arg "--disable=traefik@server:0"
        --k3s-arg "--disable=servicelb@server:0"
        --kubeconfig-update-default=false
        --kubeconfig-switch-context=false
        --wait --timeout "${START_TIMEOUT_S}s"
    )
    # A host on cgroup version 1 (WSL without cgroup_no_v1=all) needs the kubelet told to run there anyway
    if [ "$(docker info --format '{{.CgroupVersion}}')" = "1" ]; then
        arguments+=(--k3s-arg "--kubelet-arg=fail-cgroupv1=false@server:*")
    fi
    echo "== Creating the k3d cluster $CLUSTER (node ports $NODE_PORTS on 127.0.0.1)"
    "$K3D" "${arguments[@]}"
}

# The release's facts the script needs, from release.json: its chart's release name and namespace, the image tag,
# the images a control node and this worker node need, and the worker node's defaults.
read_release() {
    local bundle="$1"
    [ -f "$bundle/release.json" ] || fail "$bundle holds no release.json; build a bundle with ./build.sh --release <folder>"
    [ -f "$bundle/chart/release.json" ] || fail "$bundle/chart holds no copy of release.json; build the bundle again"
    local facts
    facts="$("$(release_python)" -I - "$bundle/release.json" "${SCENEGEMS_LOCAL_COMPONENTS:-}" <<'PYTHON'
import json
import sys

release = json.load(open(sys.argv[1], encoding="utf-8"))
if release.get("format") != 2:
    sys.exit(f"release format {release.get('format')!r}: this script installs format 2 (a chart)")
roles = release["roles"]
components_parameter = roles["worker-node"]["parameters"]["SCENEGEMS_WORKER_NODE_COMPONENTS"]
components = [part.strip() for part in (sys.argv[2] or components_parameter["default"]).split(",") if part.strip()]
images = set(roles["control-node"]["images"]) | set(roles["worker-node"]["images"])
for component in components:
    if component not in components_parameter["items"]["images"]:
        sys.exit(f"unknown component {component}")
    images.update(components_parameter["items"]["images"][component])
chart = release["chart"]
print(chart["helm_release"])
print(chart["namespace"])
print(chart["values"]["imageTag"])
print(release["revision"])
print(",".join(components))
print(roles["worker-node"]["parameters"]["SCENEGEMS_WORKER_NODE_SLOTS"]["default"])
tag = chart["values"]["imageTag"]
print(" ".join(sorted(image for image in images if image.endswith(":" + tag))))  # built by SceneGEMS, named with the release's tag
print(" ".join(sorted(image for image in images if not image.endswith(":" + tag))))  # pulled (Postgres), with their own tag
PYTHON
)" || fail "cannot read $bundle/release.json"
    facts="$(printf '%s\n' "$facts" | tr -d '\r')"  # a Windows Python ends its lines with CR LF
    {
        read -r HELM_RELEASE
        read -r NAMESPACE
        read -r IMAGE_TAG
        read -r REVISION
        read -r COMPONENTS
        read -r DEFAULT_SLOTS
        read -r BUILT_IMAGES
        read -r PULLED_IMAGES
    } <<<"$facts"
    IMAGES="$BUILT_IMAGES $PULLED_IMAGES"
}

write_values() {
    local node="$1" components="$2" slots="${SCENEGEMS_LOCAL_SLOTS:-$DEFAULT_SLOTS}"
    local yaml_components="" yaml_slots="" item
    IFS=',' read -ra items <<<"$components"
    for item in "${items[@]}"; do yaml_components+="      - $item"$'\n'; done
    IFS=',' read -ra items <<<"$slots"
    for item in "${items[@]}"; do yaml_slots+="        ${item%%:*}: ${item#*:}"$'\n'; done
    mkdir -p "$STATE"
    # A hand-written values file: each field a worker node entry leaves out takes workerNodeDefaults, and every image
    # left out is <repository>:<imageTag>, the name the images were imported under
    cat >"$VALUES_FILE" <<VALUES
controlNodeId: $CLUSTER
revision: "$REVISION"
imageTag: "$IMAGE_TAG"
imagePullPolicy: IfNotPresent
controlNode:
  enabled: true
  node: $node
workerNodes:
  - name: $WORKER_NODE
    node: $node
    machine: "$(hostname)"
    components:
${yaml_components}    slots:
${yaml_slots}
VALUES
}

# The release's images into the cluster's node by tag. A pulled image (Postgres) is a multi-platform index of which
# Docker Desktop holds one platform, and containerd refuses an archive that names content it lacks (and with it
# every other image of the same import), so pulled images are saved for the node's platform first. k3d reports
# success even when containerd refused the archive, so the node's images are checked afterwards.
import_images() {
    echo "== Importing the release's images ($IMAGE_TAG) into $CLUSTER"
    # shellcheck disable=SC2086
    "$K3D" image import $BUILT_IMAGES --cluster "$CLUSTER"
    if [ -n "$PULLED_IMAGES" ]; then
        local platform archive="$STATE/pulled-images.tar"
        platform="linux/$(docker info --format '{{.Architecture}}' | sed 's/x86_64/amd64/; s/aarch64/arm64/')"
        # shellcheck disable=SC2086
        docker save --platform "$platform" -o "$archive" $PULLED_IMAGES
        "$K3D" image import "$archive" --cluster "$CLUSTER"
        rm -f "$archive"
    fi
    local present image missing=()
    present="$(MSYS_NO_PATHCONV=1 docker exec "k3d-$CLUSTER-server-0" ctr -n k8s.io images ls -q)"
    for image in $IMAGES; do
        grep -qE "(^|/)${image//./\.}\$" <<<"$present" || missing+=("$image")
    done
    [ ${#missing[@]} -eq 0 ] || fail "the cluster's node did not take these images: ${missing[*]}"
}

up() {
    local bundle="${1:-}"
    [ -n "$bundle" ] || fail "up needs the release bundle folder: local_cluster.sh up <folder>"
    tools
    read_release "$bundle"
    local image missing=()
    for image in $IMAGES; do
        docker image inspect "$image" >/dev/null 2>&1 || missing+=("$image")
    done
    [ ${#missing[@]} -eq 0 ] || fail "these images of the release are not in Docker: ${missing[*]}; build them with ./build.sh --release <folder>"

    cluster_exists || create_cluster
    mkdir -p "$STATE"
    "$K3D" kubeconfig get "$CLUSTER" >"$KUBECONFIG_FILE"
    local node
    node="$(kubectl_ get nodes -o jsonpath='{.items[0].metadata.name}')"

    import_images

    write_values "$node" "$COMPONENTS"
    echo "== Installing $HELM_RELEASE into the namespace $NAMESPACE (values: $VALUES_FILE)"
    helm_ upgrade --install "$HELM_RELEASE" "$bundle/chart" --namespace "$NAMESPACE" --create-namespace \
        -f "$VALUES_FILE" --wait --timeout 10m
    status
    echo ""
    echo "The operator API: $0 forward, then add the cluster http://127.0.0.1:$LOCAL_PORT in the web console."
    echo "kubectl for this cluster: kubectl --kubeconfig $KUBECONFIG_FILE -n $NAMESPACE get pods"
}

namespace_of_release() {
    NAMESPACE="$(helm_ list --all-namespaces --output json | "$(release_python)" -I -c 'import json, sys; releases = json.load(sys.stdin); print(releases[0]["namespace"] if releases else "scenegems")')"
}

forward() {
    tools
    [ -f "$KUBECONFIG_FILE" ] || fail "no cluster $CLUSTER here (no $KUBECONFIG_FILE); create it with up"
    namespace_of_release
    echo "== The operator API of $CLUSTER on http://127.0.0.1:$LOCAL_PORT (Ctrl+C ends the forward)"
    kubectl_ --namespace "$NAMESPACE" port-forward service/control-node-api "$LOCAL_PORT:5174"
}

status() {
    tools
    [ -f "$KUBECONFIG_FILE" ] || fail "no cluster $CLUSTER here (no $KUBECONFIG_FILE); create it with up"
    namespace_of_release
    kubectl_ --namespace "$NAMESPACE" get deployments,statefulsets,pods -o wide
}

down() {
    tools
    if cluster_exists; then
        echo "== Deleting the k3d cluster $CLUSTER with its volumes"
        "$K3D" cluster delete "$CLUSTER"
    fi
    rm -rf "$STATE"
}

case "${1:-}" in
    up) shift; up "$@" ;;
    forward) forward ;;
    status) status ;;
    down) down ;;
    -h | --help | help) usage 0 ;;
    *) usage 1 ;;
esac
