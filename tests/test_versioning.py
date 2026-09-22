from importlib import metadata
from unittest.mock import MagicMock

import pytest

from ffmpeg4discord import versioning
from ffmpeg4discord.versioning import (
    VersionInfo,
    _get_version_from_pyproject,
    _is_newer_version,
    _version_key,
    check_for_update,
    get_current_version,
    get_latest_pypi_version,
)


def raise_(exc):
    """Return a function that raises `exc`, for patching in failures."""

    def _raise(*args, **kwargs):
        raise exc

    return _raise


def test_version_key_non_numeric_falls_back():
    assert _version_key("dev") == (0, 0, 0, "dev")


@pytest.mark.parametrize(
    "candidate, current, newer",
    [("0.2.0", "0.1.9", True), ("0.1.9", "0.1.9", False)],
)
def test_is_newer_version(candidate, current, newer):
    assert _is_newer_version(candidate, current) is newer


@pytest.mark.parametrize(
    "current, latest, available",
    [("0.1.9", "0.2.0", True), ("0.1.9", "0.1.9", False)],
)
def test_update_available(current, latest, available):
    assert VersionInfo(current_version=current, latest_version=latest).update_available is available


def test_get_current_version_falls_back_to_pyproject(monkeypatch):
    monkeypatch.setattr(versioning.metadata, "version", raise_(metadata.PackageNotFoundError))
    assert get_current_version() is not None


def test_get_current_version_unexpected_error_returns_none(monkeypatch):
    monkeypatch.setattr(versioning.metadata, "version", raise_(Exception("boom")))
    assert get_current_version() is None


def test_get_latest_pypi_version(monkeypatch):
    # urlopen is used as a context manager, so the response comes from __enter__
    response = MagicMock()
    response.__enter__.return_value.read.return_value = b'{"info": {"version": "9.9.9"}}'
    monkeypatch.setattr(versioning.urllib.request, "urlopen", lambda *args, **kwargs: response)
    assert get_latest_pypi_version(timeout_s=0.01) == "9.9.9"


def test_get_latest_pypi_version_network_error_returns_none(monkeypatch):
    monkeypatch.setattr(versioning.urllib.request, "urlopen", raise_(Exception("no net")))
    assert get_latest_pypi_version(timeout_s=0.01) is None


def test_get_version_from_pyproject_missing_file(monkeypatch):
    monkeypatch.setattr(versioning.Path, "exists", lambda self: False)
    assert _get_version_from_pyproject() is None


def test_get_version_from_pyproject_without_version(monkeypatch):
    monkeypatch.setattr(versioning.Path, "exists", lambda self: True)
    monkeypatch.setattr(versioning.Path, "read_text", lambda self, **kwargs: "[project]\nname='ffmpeg4discord'\n")
    assert _get_version_from_pyproject() is None


def test_get_version_from_pyproject_unexpected_error_returns_none(monkeypatch):
    monkeypatch.setattr(versioning.Path, "resolve", raise_(Exception("boom")))
    assert _get_version_from_pyproject() is None


def test_check_for_update_survives_network_failure(monkeypatch):
    monkeypatch.setattr(versioning, "get_latest_pypi_version", lambda **kwargs: None)
    info = check_for_update(timeout_s=0.01)
    assert info.current_version is not None  # read from pyproject.toml in this repo
    assert info.latest_version is None
    assert not info.update_available
