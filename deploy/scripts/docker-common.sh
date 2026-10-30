#!/usr/bin/env bash
# Docker image fingerprinting and build helpers of build.sh.

docker_common_init() {
    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
    cd "$SCRIPT_DIR"
    export REPO_ROOT="$SCRIPT_DIR"
    UPSTREAM_PINS_FILE="$SCRIPT_DIR/deploy/images/upstream_pins.env"
}

fingerprint_find_excluded_files() {
    local root="$1"
    find "$root" -type f \
        ! -path '*/node_modules/*' \
        ! -path '*/.git/*' \
        ! -path '*/__pycache__/*' \
        ! -path '*/env/*' \
        ! -path '*/venv/*' \
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

# Upstream source pins: every KEY=VALUE line of deploy/images/upstream_pins.env whose KEY a
# Dockerfile declares with ARG is passed to that image's docker build, and the pins file is
# then part of the image fingerprint.

# Prints the --build-arg flags, one word per line, for the pins the Dockerfile declares.
upstream_pin_build_args() {
    local dockerfile="$1"
    local line key
    [ -f "$UPSTREAM_PINS_FILE" ] || return 0
    while IFS= read -r line || [ -n "$line" ]; do
        line="${line%$'\r'}"
        case "$line" in
            '' | '#'*) continue ;;
        esac
        key="${line%%=*}"
        if grep -Eq "^[[:space:]]*ARG[[:space:]]+${key}([[:space:]=]|\$)" "$dockerfile"; then
            printf '%s\n' --build-arg "$line"
        fi
    done <"$UPSTREAM_PINS_FILE"
}

dockerfile_uses_upstream_pins() {
    [ -n "$(upstream_pin_build_args "$1")" ]
}

# Image fingerprints. A fingerprint is the sha256 of a sorted list of "relative path, content hash"
# lines over the image's inputs, so the same commit gives the same value on every machine:
# paths are relative to the repository root, text files are hashed with LF line endings (whatever
# core.autocrlf checked out) and the order does not depend on the argument order or the locale.
# The fingerprint is stored in the built image as a label, which is what a node reports.
IMAGE_FINGERPRINT_LABEL="org.scenegems.fingerprint"

# Prints the path relative to the repository root. Fails for a path outside the repository.
fingerprint_relative_path() {
    local path="$1"
    path="${path#"$REPO_ROOT"/}"
    path="${path#./}"
    case "$path" in
        /* | [A-Za-z]:*)
            echo "Fingerprint input outside the repository: $1" >&2
            return 1
            ;;
    esac
    printf '%s\n' "$path"
}

# Prints the sorted, de-duplicated relative paths of the files in the files and folders given.
fingerprint_input_files() {
    local path rel
    for path in "$@"; do
        rel=$(fingerprint_relative_path "$path") || return 1
        if [ -f "$rel" ]; then
            printf '%s\n' "$rel"
        elif [ -d "$rel" ]; then
            fingerprint_find_excluded_files "$rel"
        fi
    done | sed 's#^\./##' | LC_ALL=C sort -u
}

# Hashes the files listed on stdin in a few batched processes, not one process per file. Text
# files (grep -I) go through sed as one stream, each introduced by its path, with CRLF turned
# into LF; binary and empty files are hashed as they are, one "hash  path" line each.
fingerprint_hash_files() {
    local files binaries texts
    files=$(cat)
    [ -n "$files" ] || return 0
    binaries=$(printf '%s\n' "$files" | xargs -d '\n' grep -IL '' || true)
    texts=$(printf '%s\n' "$files" | grep -vxF -f <(printf '%s\n' "$binaries") || true)
    echo "text"
    if [ -n "$texts" ]; then
        printf '%s\n' "$texts" | xargs -d '\n' sed -s -e '1F' -e 's/\r$//' | sha256sum | awk '{print $1}'
    fi
    echo "binary"
    if [ -n "$binaries" ]; then
        printf '%s\n' "$binaries" | xargs -d '\n' sha256sum | sed 's/^\([0-9a-f]*\) [ *]/\1  /'
    fi
}

fingerprint_paths() {
    local files
    files=$(fingerprint_input_files "$@") || return 1
    printf '%s\n' "$files" | fingerprint_hash_files | sha256sum | awk '{print $1}'
}

# The Dockerfile, the given paths and, for an image that declares pins, the pins file.
fingerprint_image_inputs() {
    local dockerfile="$1"
    shift
    if dockerfile_uses_upstream_pins "$dockerfile"; then
        fingerprint_paths "$dockerfile" "$@" "$UPSTREAM_PINS_FILE"
    else
        fingerprint_paths "$dockerfile" "$@"
    fi
}

fingerprint_docker_context() {
    fingerprint_image_inputs "$1" "$2"
}

docker_build_image() {
    local tag="$1"
    local dockerfile="$2"
    local context_dir="$3"
    local fingerprint="$4"
    local build_args=()
    local arg
    while IFS= read -r arg; do
        build_args+=("$arg")
    done < <(upstream_pin_build_args "$dockerfile")
    docker build ${build_args[@]+"${build_args[@]}"} --label "$IMAGE_FINGERPRINT_LABEL=$fingerprint"         -f "$dockerfile" -t "$tag" "$context_dir"
}

image_exists() {
    docker image inspect "$1" >/dev/null 2>&1
}

# Prints the fingerprint stored in the image, empty when there is none.
image_fingerprint_label() {
    docker image inspect --format "{{ index .Config.Labels \"$IMAGE_FINGERPRINT_LABEL\" }}" "$1" 2>/dev/null | tr -d '\r\n'
}

# Builds the image unless it already carries this fingerprint. With DOCKER_FINGERPRINT_ONLY=1 it
# prints "tag fingerprint" instead, which is how the fingerprints of a checkout are listed.
build_with_fingerprint() {
    local tag="$1"
    local dockerfile="$2"
    local context_dir="$3"
    local fingerprint="$4"

    if [ "${DOCKER_FINGERPRINT_ONLY:-0}" = "1" ]; then
        echo "$tag $fingerprint"
        return
    fi
    if [ "${DOCKER_BUILD_SKIP_CHECK:-0}" = "1" ]; then
        echo "Building $tag (--no-check)..."
    elif [ "$(image_fingerprint_label "$tag")" = "$fingerprint" ]; then
        echo "Image $tag is up to date."
        return
    else
        echo "Building $tag..."
    fi
    docker_build_image "$tag" "$dockerfile" "$context_dir" "$fingerprint"
}

build_if_stale() {
    local tag="$1"
    local dockerfile="$2"
    local context_dir="$3"
    build_with_fingerprint "$tag" "$dockerfile" "$context_dir" "$(fingerprint_image_inputs "$dockerfile" "$context_dir")"
}

build_subsystem_if_stale() {
    local tag="$1"
    local dockerfile="$2"
    shift 2
    build_with_fingerprint "$tag" "$dockerfile" "$SCRIPT_DIR" "$(fingerprint_image_inputs "$dockerfile" "$@")"
}
