#!/usr/bin/env python3
"""Keep housefly.vome.io's public guest sign-ins alive.

/demo, /swarm and /housewad are 302s to one-click guest logins on the hosted
demo homes. A guest link lasts at most 30 days, so this runs daily (systemd
timer, see housefly-guest-links.timer) and reissues any link with less than a
week left: in practice, once a month per link.

The links themselves are not in this repository. The job writes them to
/etc/nginx/housefly-guest-links.conf (root only), which the site config
includes, then checks the config and reloads nginx; a config that fails the
check is put back and the job fails. Old links are left to the portal's own
expiry sweep (portal/guest_link_expiry.py), so a visitor already playing is
not thrown out mid-game.

Run as root:
    /var/www/vome.home.live/venv/bin/python renew_guest_links.py [--force] [--dry-run]
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import shutil
import subprocess
import sys
import tempfile
import time

PORTAL = "/var/www/vome.home.live"
STATE = "/var/lib/housefly-guest-links/state.json"
INCLUDE = "/etc/nginx/housefly-guest-links.conf"

DAY = 24 * 60 * 60
LIFETIME = 30 * DAY
RENEW_WITHIN = 7 * DAY

# (path on housefly.vome.io, hosted instance, dashboard the guest lands on)
LINKS = [
    ("/demo", "748d339f-ae52-4cc3-81d7-f7c93f1a8852", "lovelace/fly"),
    ("/swarm", "b13509eb-dba0-45e0-8034-5ba03794639d", "fly-swarm"),
    ("/housewad", "748d339f-ae52-4cc3-81d7-f7c93f1a8852", "house-wad/clip"),
]

log = logging.getLogger("housefly-guest-links")


def load_state() -> dict:
    try:
        with open(STATE) as f:
            return json.load(f)
    except FileNotFoundError:
        return {}


def save_state(state: dict) -> None:
    os.makedirs(os.path.dirname(STATE), mode=0o700, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(STATE))
    with os.fdopen(fd, "w") as f:
        json.dump(state, f, indent=1)
    os.chmod(tmp, 0o600)
    os.replace(tmp, STATE)


def render_include(state: dict) -> str:
    lines = [
        "# Written by HouseFly site/renew_guest_links.py -- do not edit by hand.",
        "# Public demo guest sign-ins; reissued before they expire.",
    ]
    for path, server_id, dashboard in LINKS:
        entry = state.get(path)
        if not entry:
            continue
        expires = time.strftime("%Y-%m-%d", time.gmtime(entry["expires_at"]))
        lines += [
            f"# {path}: {dashboard} on {server_id}, expires {expires}",
            f"location = {path} {{",
            f'    return 302 "{entry["url"]}";',
            "}",
        ]
    return "\n".join(lines) + "\n"


def install_include(text: str) -> None:
    """Write the include, check nginx, reload; put the old one back on failure."""
    backup = None
    if os.path.exists(INCLUDE):
        backup = INCLUDE + ".prev"
        shutil.copy2(INCLUDE, backup)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(INCLUDE))
    with os.fdopen(fd, "w") as f:
        f.write(text)
    os.chmod(tmp, 0o600)
    os.replace(tmp, INCLUDE)
    check = subprocess.run(["nginx", "-t"], capture_output=True, text=True)
    if check.returncode != 0:
        if backup:
            os.replace(backup, INCLUDE)
        raise RuntimeError(f"nginx -t failed, previous links restored: {check.stderr.strip()}")
    subprocess.run(["systemctl", "reload", "nginx"], check=True)


def issue(server_id: str, dashboard: str) -> dict:
    # The jobs role: the portal must not start its web-role watchers here.
    os.environ["VOME_ROLE"] = "jobs"
    sys.path.insert(0, PORTAL)
    os.chdir(PORTAL)
    from portal.app import app
    from portal.ha_guest_links import create_guest_link
    from portal.models import get_server

    with app.app_context():
        server = get_server(server_id)
        if not server:
            raise RuntimeError(f"no such instance {server_id}")
        result, error = create_guest_link(
            server,
            dashboard=dashboard,
            expires_in=LIFETIME,
            created_by_user_id=server.get("user_id"),
        )
    if error:
        raise RuntimeError(f"{server_id}: {error}")
    return {"id": result["id"], "url": result["url"], "expires_at": result["expires_at"]}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--force", action="store_true", help="reissue every link now")
    parser.add_argument("--dry-run", action="store_true", help="say what would be reissued and stop")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    # The portal logs every command it runs on the container host, and the
    # one that mints a guest token carries the guest's password. Keep that
    # out of the journal.
    for noisy in ("portal", "paramiko"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    state = load_state()
    now = int(time.time())
    due = [
        (path, server_id, dashboard)
        for path, server_id, dashboard in LINKS
        if args.force or path not in state or state[path]["expires_at"] - now < RENEW_WITHIN
    ]
    for path, _, _ in LINKS:
        if path in state:
            left = (state[path]["expires_at"] - now) / DAY
            log.info("%s: %.1f days left%s", path, left, " -> reissue" if any(d[0] == path for d in due) else "")
        else:
            log.info("%s: no link on record -> issue", path)
    if args.dry_run:
        return 0

    for path, server_id, dashboard in due:
        state[path] = issue(server_id, dashboard)
        save_state(state)
        log.info("%s: new link %s, expires %s", path, state[path]["id"],
                 time.strftime("%Y-%m-%d", time.gmtime(state[path]["expires_at"])))

    if due or not os.path.exists(INCLUDE):
        install_include(render_include(state))
        log.info("nginx reloaded with %d links", len(state))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # noqa: BLE001 -- the unit's status is the alert
        log.error("guest link renewal failed: %s", exc)
        sys.exit(1)
