#!/usr/bin/env bash
# Bring up the HouseFly testbed.
set -euo pipefail
cd "$(dirname "$0")"
python3 generate_house.py
docker compose up -d
echo
echo "Testbed starting on http://localhost:8124"
echo "First run takes a minute or two while Home Assistant onboards."
echo "Then: Settings -> Devices & Services -> Add Integration -> HouseFly"
echo "Logs: docker compose logs -f homeassistant"
