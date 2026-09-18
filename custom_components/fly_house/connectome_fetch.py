"""Fetch the connectome data pack when it is not on disk.

The pack ships inside the integration and that remains the normal case -- HACS,
a git clone and a manual copy all bring it along, and nothing here runs. It
exists for installs where the files arrive by a route that cannot carry 432 KB
of binary: a text-only file API, a constrained deployment pipeline, some
sandbox that strips anything that is not source.

Two properties matter more than convenience here:

* **It is verified.** The expected SHA-256 of each file is compiled in. A
  download that does not match is discarded, not used. This is measurement data
  the whole model rests on; silently running on something else would make every
  number the README quotes meaningless.
* **It is pinned to this version.** The URL carries the integration's own
  version tag, so the pack always matches the code that reads it. Fetching
  "latest" would mean a future pack quietly loaded by today's loader.

`np.load` on an .npz does not unpickle by default, so this is data rather than
code either way -- but a checksum costs nothing and the failure mode without
one is invisible.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from pathlib import Path

from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

_LOGGER = logging.getLogger(__name__)

RAW_BASE = "https://raw.githubusercontent.com/Vortitron/HouseFly"

# sha256 of each shipped file. Regenerate with:
#   sha256sum custom_components/fly_house/connectome/*
EXPECTED = {
    "core.npz": "689f651ebcc1887205b5097684d0a2d6eb445ed26b76fed45d2a6476ad310ba9",
    "meta.json.gz": "3bff307f39e8ed996ce6b61904a832e06a63327f5fb4fe0e7663fbada6510239",
}

DOWNLOAD_TIMEOUT = 120


def _version() -> str:
    manifest = Path(__file__).parent / "manifest.json"
    return json.loads(manifest.read_text())["version"]


def _digest(path: Path) -> str:
    sha = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(65536), b""):
            sha.update(block)
    return sha.hexdigest()


def missing_files(directory: Path) -> list[str]:
    """Which pack files are absent or do not match their expected digest."""
    bad: list[str] = []
    for name, expected in EXPECTED.items():
        path = directory / name
        if not path.is_file():
            bad.append(name)
        elif _digest(path) != expected:
            _LOGGER.warning(
                "HouseFly connectome file %s does not match its expected checksum "
                "and will be re-fetched", name,
            )
            bad.append(name)
    return bad


async def async_ensure_connectome(hass: HomeAssistant, directory: Path) -> bool:
    """Make sure the pack is present and intact. Returns True if it is usable.

    Does nothing at all when the files are already correct, which is the normal
    case for every supported install route.
    """
    wanted = await hass.async_add_executor_job(missing_files, directory)
    if not wanted:
        return True

    version = await hass.async_add_executor_job(_version)
    _LOGGER.warning(
        "HouseFly connectome pack incomplete (%s). Fetching the v%s pack from "
        "GitHub -- this normally ships with the integration and only needs "
        "downloading when the files arrived by a route that could not carry "
        "them.", ", ".join(wanted), version,
    )

    session = async_get_clientsession(hass)
    await hass.async_add_executor_job(directory.mkdir, 0o755, True, True)

    for name in wanted:
        url = f"{RAW_BASE}/v{version}/custom_components/fly_house/connectome/{name}"
        try:
            async with asyncio.timeout(DOWNLOAD_TIMEOUT):
                response = await session.get(url)
                response.raise_for_status()
                payload = await response.read()
        except Exception as err:  # noqa: BLE001 -- network, DNS, HTTP, timeout
            _LOGGER.error("HouseFly could not fetch %s: %s", url, err)
            return False

        actual = hashlib.sha256(payload).hexdigest()
        if actual != EXPECTED[name]:
            # Refuse it. Running the model on a pack we cannot identify would
            # invalidate every measured claim the integration makes.
            _LOGGER.error(
                "HouseFly refused the downloaded %s: expected sha256 %s, got %s",
                name, EXPECTED[name], actual,
            )
            return False

        await hass.async_add_executor_job((directory / name).write_bytes, payload)
        _LOGGER.info("HouseFly fetched %s (%d bytes, checksum verified)",
                     name, len(payload))

    return True
