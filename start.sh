#!/usr/bin/env bash
set -euo pipefail

source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/scripts/docker-common.sh"
docker_common_init

require_image "scenegems-frontend:dev"
require_image "scenegems-backend:latest"
require_image "scenegems-mqtt-broker"

ensure_compose_volumes

trap shutdown_stack EXIT INT TERM

echo "Starting frontend..."
compose_cmd up -d frontend

echo "Starting MQTT broker and backend..."
compose_cmd up -d broker backend

echo ""
echo "SceneGEMS stack is running:"
echo "  Frontend:  http://localhost:5173"
echo "  Backend:   http://localhost:8000/health"
echo "  MQTT:      localhost:1882 (host) / broker:1883 (compose network)"
echo ""
echo "Streaming backend logs (Ctrl+C stops the full stack)..."

compose_cmd logs -f backend
