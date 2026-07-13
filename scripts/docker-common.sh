#!/usr/bin/env bash
# Shared Docker image fingerprinting and build helpers for build.sh / start.sh.

docker_common_init() {
    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
    cd "$SCRIPT_DIR"
    export REPO_ROOT="$SCRIPT_DIR"
    COMPOSE_FILE="$SCRIPT_DIR/docker-compose.yml"
    COMPOSE_PROJECT_NAME="${COMPOSE_PROJECT_NAME:-scenegems}"
}

compose_cmd() {
    if docker compose version >/dev/null 2>&1; then
        docker compose -f "$COMPOSE_FILE" -p "$COMPOSE_PROJECT_NAME" "$@"
    else
        docker-compose -f "$COMPOSE_FILE" -p "$COMPOSE_PROJECT_NAME" "$@"
    fi
}

stamp_path_for_tag() {
    local tag="$1"
    local safe_tag="${tag//[:]/_}"
    echo "$SCRIPT_DIR/.docker-stamps/${safe_tag}.sha256"
}

fingerprint_find_excluded_files() {
    local root="$1"
    find "$root" -type f \
        ! -path '*/node_modules/*' \
        ! -path '*/.git/*' \
        ! -path '*/__pycache__/*' \
        ! -path '*/env/*' \
        ! -path '*/venv/*' \
        ! -path '*/.docker-stamps/*' \
        ! -path '*/dist/*' \
        ! -path '*/dist-ssr/*' \
        ! -path '*/.mypy_cache/*' \
        ! -path '*/.pytest_cache/*' \
        ! -path '*/website/build/*' \
        ! -path '*/public/docs/*' \
        ! -path '*/.egg-info/*' \
        ! -path '*/assets/gen_data/*' \
        ! -path '*/assets/images/exported_plots/*' \
        ! -path '*/runtime_assets/*/gen_tmp/*'
}

fingerprint_docker_context() {
    local dockerfile="$1"
    local context_dir="$2"
    {
        sha256sum "$dockerfile"
        fingerprint_find_excluded_files "$context_dir" | LC_ALL=C sort | while IFS= read -r file; do
            sha256sum "$file"
        done
    } | sha256sum | awk '{print $1}'
}

fingerprint_paths() {
    local path
    {
        for path in "$@"; do
            if [ -f "$path" ]; then
                sha256sum "$path"
            elif [ -d "$path" ]; then
                fingerprint_find_excluded_files "$path" | LC_ALL=C sort | while IFS= read -r file; do
                    sha256sum "$file"
                done
            fi
        done
    } | sha256sum | awk '{print $1}'
}

image_exists() {
    docker image inspect "$1" >/dev/null 2>&1
}

write_build_stamp() {
    local tag="$1"
    local fingerprint="$2"
    local stamp_path
    stamp_path=$(stamp_path_for_tag "$tag")
    mkdir -p "$(dirname "$stamp_path")"
    printf '%s\n' "$fingerprint" >"$stamp_path"
}

build_if_stale() {
    local tag="$1"
    local dockerfile="$2"
    local context_dir="$3"
    local fingerprint stamp_path stored

    if [ "${DOCKER_BUILD_SKIP_CHECK:-0}" = "1" ]; then
        echo "Building $tag (--no-check)..."
        docker build -f "$dockerfile" -t "$tag" "$context_dir"
        fingerprint=$(fingerprint_docker_context "$dockerfile" "$context_dir")
        write_build_stamp "$tag" "$fingerprint"
        return
    fi

    echo "Checking image $tag..."
    fingerprint=$(fingerprint_docker_context "$dockerfile" "$context_dir")
    stamp_path=$(stamp_path_for_tag "$tag")
    stored=""
    if [ -f "$stamp_path" ]; then
        stored=$(tr -d '\r\n' <"$stamp_path")
    fi

    if [ "$fingerprint" = "$stored" ] && image_exists "$tag"; then
        echo "Image $tag is up to date."
        return
    fi

    echo "Building $tag..."
    docker build -f "$dockerfile" -t "$tag" "$context_dir"
    write_build_stamp "$tag" "$fingerprint"
}

build_subsystem_if_stale() {
    local tag="$1"
    local dockerfile="$2"
    shift 2
    local fingerprint stamp_path stored

    if [ "${DOCKER_BUILD_SKIP_CHECK:-0}" = "1" ]; then
        echo "Building $tag (--no-check)..."
        docker build -f "$dockerfile" -t "$tag" "$SCRIPT_DIR"
        fingerprint=$(fingerprint_paths "$dockerfile" "$@")
        write_build_stamp "$tag" "$fingerprint"
        return
    fi

    echo "Checking image $tag..."
    fingerprint=$(fingerprint_paths "$dockerfile" "$@")
    stamp_path=$(stamp_path_for_tag "$tag")
    stored=""
    if [ -f "$stamp_path" ]; then
        stored=$(tr -d '\r\n' <"$stamp_path")
    fi

    if [ "$fingerprint" = "$stored" ] && image_exists "$tag"; then
        echo "Image $tag is up to date."
        return
    fi

    echo "Building $tag..."
    docker build -f "$dockerfile" -t "$tag" "$SCRIPT_DIR"
    write_build_stamp "$tag" "$fingerprint"
}

require_image() {
    local tag="$1"
    if ! image_exists "$tag"; then
        echo "Missing image $tag. Run ./build.sh first." >&2
        exit 1
    fi
}

ensure_compose_volumes() {
    docker volume inspect scenegems_runtime_assets >/dev/null 2>&1 \
        || docker volume create scenegems_runtime_assets >/dev/null
    docker volume inspect scenegems_broker_data >/dev/null 2>&1 \
        || docker volume create scenegems_broker_data >/dev/null
}

shutdown_stack() {
    echo "Shutting down SceneGEMS stack..."
    if docker ps --format '{{.Names}}' 2>/dev/null | grep -qx "scenegems_backend"; then
        docker exec scenegems_backend python - <<'PY' 2>/dev/null || true
from scenegems_tool.docker_subsystem_shutdown import shutdown_all_docker_subsystems
shutdown_all_docker_subsystems()
PY
    fi
    compose_cmd down --remove-orphans 2>/dev/null || true
}
