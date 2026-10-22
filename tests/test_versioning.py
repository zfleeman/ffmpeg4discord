from importlib import metadata
from unittest.mock import MagicMock

import pytest

from ffmpeg4discord import versioning
from ffmpeg4discord.versioning import VersionInfo, check_for_update, get_latest_pypi_version


def raise_(exc):
    """Return a function that raises `exc`, for patching in failures."""

    def _raise(*args, **kwargs):
        raise exc

    return _raise


@pytest.mark.parametrize(
    "current, latest, available",
    [
        ("0.1.9", "0.2.0", True),
        ("0.1.9", "0.1.9", False),
        ("0.4.9", "0.4.10", True),  # compared as numbers, not text
        ("0.5.0", "0.4.1", False),  # a newer local build
        ("dev", "0.4.1", True),  # an unreadable version counts as oldest
        ("0.4.1", None, False),  # PyPI couldn't be reached
        (None, "0.4.1", False),
    ],
)
def test_update_available(current, latest, available):
    assert VersionInfo(current_version=current, latest_version=latest).update_available is available


def test_get_latest_pypi_version(monkeypatch):
    # urlopen is used as a context manager, so the response comes from __enter__
    response = MagicMock()
    response.__enter__.return_value.read.return_value = b'{"info": {"version": "9.9.9"}}'
    monkeypatch.setattr(versioning.urllib.request, "urlopen", lambda *args, **kwargs: response)
    assert get_latest_pypi_version() == "9.9.9"


def test_get_latest_pypi_version_network_error_returns_none(monkeypatch):
    monkeypatch.setattr(versioning.urllib.request, "urlopen", raise_(OSError("no net")))
    assert get_latest_pypi_version() is None


def test_check_for_update(monkeypatch):
    monkeypatch.setattr(versioning, "get_latest_pypi_version", lambda: "9.9.9")
    info = check_for_update()
    assert info.current_version == metadata.version("ffmpeg4discord")
    assert info.update_available


def test_check_for_update_without_installed_package(monkeypatch):
    monkeypatch.setattr(versioning.metadata, "version", raise_(metadata.PackageNotFoundError))
    monkeypatch.setattr(versioning, "get_latest_pypi_version", lambda: "9.9.9")
    assert check_for_update() == VersionInfo(current_version=None, latest_version="9.9.9")
