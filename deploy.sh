#!/bin/bash
set -e

# Usage: ./deploy.sh [build|start|stop|restart|logs|status]

ACTION="${1:-start}"

# Validate required config files
for f in config/client.json config/platform.env config/calendar-key.json config/azure_refresh_token.txt; do
    if [ ! -f "$f" ]; then
        echo "ERROR: Missing $f"
        exit 1
    fi
done

# Create data and logs directories if they don't exist
mkdir -p data logs

case "$ACTION" in
    build)
        echo "Building Docker image..."
        docker compose build
        echo "Done."
        ;;
    start)
        echo "Starting container..."
        docker compose up -d
        sleep 3
        docker compose ps
        echo ""
        echo "Health check:"
        curl -s http://localhost:${PORT:-8001}/health || echo "Health check failed"
        ;;
    stop)
        echo "Stopping container..."
        docker compose down
        ;;
    restart)
        echo "Restarting container..."
        docker compose restart
        sleep 3
        docker compose ps
        ;;
    logs)
        docker compose logs -f --tail=50
        ;;
    status)
        docker compose ps
        echo ""
        echo "Health check:"
        curl -s http://localhost:${PORT:-8001}/health || echo "Not responding"
        ;;
    *)
        echo "Usage: ./deploy.sh [build|start|stop|restart|logs|status]"
        exit 1
        ;;
esac
