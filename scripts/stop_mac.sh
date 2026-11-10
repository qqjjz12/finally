#!/usr/bin/env bash
# Stop and remove the FinAlly container. The data volume is kept.
set -euo pipefail
if docker rm -f finally >/dev/null 2>&1; then
  echo "FinAlly stopped (volume finally-data preserved)."
else
  echo "FinAlly is not running."
fi
