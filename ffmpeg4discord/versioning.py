"""Checks PyPI for a newer ffmpeg4discord. Network failures never stop the app from starting."""

import json
import re
import urllib.request
from dataclasses import dataclass
from importlib import metadata
from typing import Optional

PACKAGE_NAME = "ffmpeg4discord"

# Seconds to wait for PyPI before giving up on the update notice
PYPI_TIMEOUT = 1.5


def _version_numbers(version: str) -> tuple[int, ...]:
    """The leading numbers of a version, e.g. (0, 4, 1) for "0.4.1" or "0.4.1rc1", so versions compare correctly."""
    match = re.match(r"\d+(\.\d+)*", version)
    return tuple(int(n) for n in match.group().split(".")) if match else ()


@dataclass(frozen=True)
class VersionInfo:
    """The installed version and the newest one on PyPI. Either is None when it couldn't be read."""

    current_version: Optional[str]
    latest_version: Optional[str]

    @property
    def update_available(self) -> bool:
        if not self.current_version or not self.latest_version:
            return False
        return _version_numbers(self.latest_version) > _version_numbers(self.current_version)


def get_latest_pypi_version() -> Optional[str]:
    """Return the newest version on PyPI, or None if PyPI can't be reached."""
    try:
        with urllib.request.urlopen(f"https://pypi.org/pypi/{PACKAGE_NAME}/json", timeout=PYPI_TIMEOUT) as resp:
            return json.load(resp)["info"]["version"]
    except Exception:
        # Offline, slow, or an unexpected response. The update notice is optional, so skip it.
        return None


def check_for_update() -> VersionInfo:
    """Compare the installed version with the newest one on PyPI."""
    try:
        current = metadata.version(PACKAGE_NAME)
    except metadata.PackageNotFoundError:  # running from source without installing
        current = None
    return VersionInfo(current_version=current, latest_version=get_latest_pypi_version())
