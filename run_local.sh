#!/bin/bash
# Local development startup script
# Usage: ./run_local.sh

set -e

# Load .env if it exists
if [ -f .env ]; then
    export $(grep -v '^#' .env | xargs)
fi

# Required env vars — set these in .env or export them before running
: "${RUNWAYML_API_SECRET:?Need to set RUNWAYML_API_SECRET}"
: "${STRIPE_SECRET_KEY:?Need to set STRIPE_SECRET_KEY}"
: "${STRIPE_PUBLISHABLE_KEY:?Need to set STRIPE_PUBLISHABLE_KEY}"
: "${STRIPE_PRICE_ID:?Need to set STRIPE_PRICE_ID}"

export LOCAL_DEV=true
export PORT=8080

echo "🚀 Starting Covertify locally on http://localhost:8080"
echo "   LOCAL_DEV=true (HTTPS enforcement disabled)"
echo "   Workers: 2 | Threads: 4 per worker"
echo ""

source venv/bin/activate
gunicorn app:app \
    --bind 0.0.0.0:$PORT \
    --workers 2 \
    --threads 4 \
    --timeout 600 \
    --log-level info
