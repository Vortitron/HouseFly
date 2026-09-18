#!/usr/bin/env bash
# Bring up the HouseFly testbed.
#
# Nothing here touches real hardware: every light and switch is a template
# helper. That is the point -- somewhere to let the fly off the lead, and
# somewhere safe to hand to other people without worrying what they toggle.
set -euo pipefail
cd "$(dirname "$0")"

DOCKER="docker"
if ! docker info >/dev/null 2>&1; then
  if sudo -n docker info >/dev/null 2>&1; then
    DOCKER="sudo docker"
  else
    echo "Cannot reach the Docker daemon. Add yourself to the docker group," >&2
    echo "or run this with sudo." >&2
    exit 1
  fi
fi

python3 generate_house.py

# Home Assistant's image is public, but a stale ghcr.io login in the Docker
# config will be sent anyway and the registry answers "denied: denied" -- which
# reads like the image is missing rather than like a credentials problem. Pull
# through a throwaway client config so no stored auth is offered. Harmless if
# you were never logged in.
if ! $DOCKER image inspect ghcr.io/home-assistant/home-assistant:stable >/dev/null 2>&1; then
  echo "Pulling Home Assistant (anonymously) ..."
  ANON="$(mktemp -d)"
  echo '{}' > "$ANON/config.json"
  $DOCKER --config "$ANON" pull ghcr.io/home-assistant/home-assistant:stable
  rm -rf "$ANON"
fi

$DOCKER compose up -d

echo
echo "Waiting for Home Assistant to answer ..."
until curl -sf -o /dev/null http://localhost:8124/; do sleep 4; done

cat <<'MSG'

Testbed up: http://localhost:8124

  1. Create an account (it is local and throwaway).
  2. Settings -> Devices & Services -> Add Integration -> HouseFly.
  3. Open the "HouseFly" dashboard in the sidebar.

Actuation is off by default. Turn it on in the integration options once you
have had a look at what it does.

Logs:  docker compose logs -f homeassistant
Stop:  docker compose down
MSG
