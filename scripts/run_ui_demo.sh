#!/usr/bin/env bash
# Run a phase of the UI-driven acceptance demo in a Playwright container (host network,
# so it reaches EVAP on 127.0.0.1). Credentials come from .env and secrets/demo_users.env.
set -euo pipefail
cd "$(dirname "$0")/.."
PHASE=${1:?usage: run_ui_demo.sh setup|demo|check}
set -a; source .env; source secrets/demo_users.env; set +a
mkdir -p docs/screenshots
docker run --rm --network host --user "$(id -u):$(id -g)" -e HOME=/tmp \
  -e EVAP_URL="http://127.0.0.1:${EVAP_HTTP_PORT:-8300}" \
  -e ADMIN_USER="$EVAP_BOOTSTRAP_ADMIN_USER" -e ADMIN_PASSWORD="$EVAP_BOOTSTRAP_ADMIN_PASSWORD" \
  -e ENG_PASSWORD -e REV_PASSWORD -e REPO_URL \
  -v "$PWD/secrets:/secrets" -v "$PWD/scripts:/scripts:ro" -v "$PWD/examples:/examples:ro" -v "$PWD/docs/screenshots:/out" \
  mcr.microsoft.com/playwright/python:v1.49.1-jammy \
  bash -c "pip install -q --user playwright==1.49.1 2>/dev/null; python /scripts/ui_demo.py $PHASE"
