"""ffmpeg4discord version helpers.

Goals:
- Determine the currently running version of ffmpeg4discord.
- Query PyPI to determine the latest published version.
- Compare versions safely without introducing extra dependencies.

Network access is best-effort: failures should never prevent the app from
starting.
"""

from __future__ import annotations

import json
import re
import urllib.request
from dataclasses import dataclass
from importlib import metadata
from pathlib import Path
from typing import Optional

PACKAGE_NAME = "ffmpeg4discord"


@dataclass(frozen=True)
class VersionInfo:
    current_version: Optional[str]
    latest_version: Optional[str]

    @property
    def update_available(self) -> bool:
        if not self.current_version or not self.latest_version:
            return False
        return _is_newer_version(self.latest_version, self.current_version)


def get_current_version(package_name: str = PACKAGE_NAME) -> Optional[str]:
    """Return the currently installed version.

    Primary source is `importlib.metadata` (works for normal and editable
    installs). As a dev convenience (running from a source checkout without an
    installed dist), falls back to reading `pyproject.toml`.
    """

    try:
        return metadata.version(package_name)
    except metadata.PackageNotFoundError:
        return _get_version_from_pyproject()
    except Exception:
        return None


def get_latest_pypi_version(package_name: str = PACKAGE_NAME, timeout_s: float = 1.5) -> Optional[str]:
    """Return the latest published version on PyPI (best-effort)."""

    url = f"https://pypi.org/pypi/{package_name}/json"
    try:
        with urllib.request.urlopen(url, timeout=timeout_s) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return data.get("info", {}).get("version")
    except Exception:
        return None


def check_for_update(package_name: str = PACKAGE_NAME, timeout_s: float = 1.5) -> VersionInfo:
    """Compute current vs latest version info."""

    current = get_current_version(package_name=package_name)
    latest = get_latest_pypi_version(package_name=package_name, timeout_s=timeout_s)
    return VersionInfo(current_version=current, latest_version=latest)


def _get_version_from_pyproject() -> Optional[str]:
    """Best-effort parsing of version from a source checkout."""

    try:
        repo_root = Path(__file__).resolve().parents[1]
        pyproject = repo_root / "pyproject.toml"
        if not pyproject.exists():
            return None

        text = pyproject.read_text(encoding="utf-8")
        # simple pattern: version = "0.1.9"
        match = re.search(r"^version\s*=\s*\"([^\"]+)\"\s*$", text, flags=re.MULTILINE)
        return match.group(1) if match else None
    except Exception:
        return None


def _is_newer_version(candidate: str, current: str) -> bool:
    """Return True if `candidate` represents a newer version than `current`.

    This is intentionally minimal (no external deps). It correctly handles the
    project's current numeric versions like 0.1.9.
    """

    return _version_key(candidate) > _version_key(current)


def _version_key(v: str) -> tuple:
    """Turn a version string into a comparable tuple.

    For versions we don't understand, falls back to the raw string.
    """

    # Accept things like "1", "1.2", "1.2.3" and ignore trailing metadata.
    match = re.match(r"^(\d+)(?:\.(\d+))?(?:\.(\d+))?", v)
    if not match:
        return (0, 0, 0, v)

    major = int(match.group(1) or 0)
    minor = int(match.group(2) or 0)
    patch = int(match.group(3) or 0)
    # Keep original for tie-breaker stability
    return (major, minor, patch, v)
