#!/usr/bin/env bash
# Thin wrapper: the build script lives in deploy/scripts.
exec "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/deploy/scripts/build.sh" "$@"
