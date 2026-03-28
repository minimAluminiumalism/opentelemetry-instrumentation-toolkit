#!/bin/bash
# Manage Prometheus container for E2E metrics verification.
#
# Usage:
#   ./prometheus.sh start    # Start Prometheus in Docker
#   ./prometheus.sh stop     # Stop and remove container
#   ./prometheus.sh status   # Check if running
#   ./prometheus.sh clean    # Stop + restart (clear all metrics)
#
# Ports:
#   9090  - Prometheus UI + Query API
#   9464  - (expected) OTel Prometheus exporter endpoint on the app side
#
# Prometheus Query API:
#   GET http://localhost:9090/api/v1/query?query=<promql>
#   GET http://localhost:9090/api/v1/label/__name__/values

set -euo pipefail

CONTAINER_NAME="otel-skills-prometheus"
IMAGE="prom/prometheus:latest"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

_write_config() {
    # Prometheus config that scrapes the OTel Prometheus exporter
    cat > /tmp/otel-skills-prometheus.yml <<'EOF'
global:
  scrape_interval: 5s
  evaluation_interval: 5s

scrape_configs:
  - job_name: "otel-genai-e2e"
    static_configs:
      - targets: ["host.docker.internal:9464"]
    # Scrape the OTel Prometheus exporter running on the host
EOF
}

start() {
    if docker ps --format '{{.Names}}' | grep -q "^${CONTAINER_NAME}$"; then
        echo "Prometheus is already running."
        echo "  UI:    http://localhost:9090"
        echo "  Query: http://localhost:9090/api/v1/query?query=..."
        return 0
    fi

    docker rm -f "$CONTAINER_NAME" 2>/dev/null || true

    _write_config

    echo "Starting Prometheus..."
    docker run -d \
        --name "$CONTAINER_NAME" \
        -p 9090:9090 \
        -v /tmp/otel-skills-prometheus.yml:/etc/prometheus/prometheus.yml:ro \
        "$IMAGE" > /dev/null

    echo -n "Waiting for Prometheus to start"
    for i in $(seq 1 30); do
        if curl -sf http://localhost:9090/-/ready > /dev/null 2>&1; then
            echo " ready."
            echo ""
            echo "  UI:    http://localhost:9090"
            echo "  Query: http://localhost:9090/api/v1/query?query=..."
            echo ""
            echo "  Scraping OTel Prometheus exporter at host:9464"
            echo "  (your E2E test should export metrics on port 9464)"
            return 0
        fi
        echo -n "."
        sleep 1
    done
    echo " timeout!"
    echo "Error: Prometheus did not start within 30 seconds." >&2
    return 1
}

stop() {
    echo "Stopping Prometheus..."
    docker rm -f "$CONTAINER_NAME" 2>/dev/null || true
    rm -f /tmp/otel-skills-prometheus.yml
    echo "Done."
}

status() {
    if docker ps --format '{{.Names}}' | grep -q "^${CONTAINER_NAME}$"; then
        echo "Prometheus is running."
        echo "  UI: http://localhost:9090"
        # Show available metrics
        metrics=$(curl -sf 'http://localhost:9090/api/v1/label/__name__/values' 2>/dev/null || echo '{"data":[]}')
        echo "  Metrics: $metrics"
    else
        echo "Prometheus is not running."
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
