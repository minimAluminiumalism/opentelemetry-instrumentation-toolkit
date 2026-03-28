#!/bin/bash
# Manage Jaeger all-in-one container for E2E trace verification.
#
# Usage:
#   ./jaeger.sh start    # Start Jaeger in Docker
#   ./jaeger.sh stop     # Stop and remove container
#   ./jaeger.sh status   # Check if running
#   ./jaeger.sh clean    # Stop + remove all traces
#
# Ports:
#   4317  - OTLP gRPC receiver (send traces here)
#   4318  - OTLP HTTP receiver
#   16686 - Jaeger UI + Query API
#
# Jaeger Query API:
#   GET http://localhost:16686/api/traces?service=<name>
#   GET http://localhost:16686/api/traces/<traceID>
#   GET http://localhost:16686/api/services

set -euo pipefail

CONTAINER_NAME="otel-skills-jaeger"
IMAGE="jaegertracing/all-in-one:latest"

start() {
    if docker ps --format '{{.Names}}' | grep -q "^${CONTAINER_NAME}$"; then
        echo "Jaeger is already running."
        echo "  UI:   http://localhost:16686"
        echo "  OTLP: http://localhost:4318 (HTTP) / localhost:4317 (gRPC)"
        return 0
    fi

    # Remove stopped container if exists
    docker rm -f "$CONTAINER_NAME" 2>/dev/null || true

    echo "Starting Jaeger all-in-one..."
    docker run -d \
        --name "$CONTAINER_NAME" \
        -p 4317:4317 \
        -p 4318:4318 \
        -p 16686:16686 \
        -e COLLECTOR_OTLP_ENABLED=true \
        "$IMAGE" > /dev/null

    # Wait for Jaeger to be ready
    echo -n "Waiting for Jaeger to start"
    for i in $(seq 1 30); do
        if curl -sf http://localhost:16686/api/services > /dev/null 2>&1; then
            echo " ready."
            echo ""
            echo "  UI:   http://localhost:16686"
            echo "  OTLP: http://localhost:4318 (HTTP) / localhost:4317 (gRPC)"
            return 0
        fi
        echo -n "."
        sleep 1
    done
    echo " timeout!"
    echo "Error: Jaeger did not start within 30 seconds." >&2
    return 1
}

stop() {
    echo "Stopping Jaeger..."
    docker rm -f "$CONTAINER_NAME" 2>/dev/null || true
    echo "Done."
}

status() {
    if docker ps --format '{{.Names}}' | grep -q "^${CONTAINER_NAME}$"; then
        echo "Jaeger is running."
        echo "  UI:   http://localhost:16686"
        # Show available services
        services=$(curl -sf http://localhost:16686/api/services 2>/dev/null || echo '{"data":[]}')
        echo "  Services: $services"
    else
        echo "Jaeger is not running."
        return 1
    fi
}

clean() {
    stop
    start
}

case "${1:-}" in
    start)  start ;;
    stop)   stop ;;
    status) status ;;
    clean)  clean ;;
    *)
        echo "Usage: $0 {start|stop|status|clean}" >&2
        exit 1
        ;;
esac
