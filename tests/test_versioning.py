# pylint: disable=C0114, C0115, C0116

import unittest
from unittest.mock import MagicMock, patch

from ffmpeg4discord.versioning import (
    VersionInfo,
    _get_version_from_pyproject,
    _is_newer_version,
    _version_key,
    check_for_update,
    get_current_version,
    get_latest_pypi_version,
)


class TestVersioning(unittest.TestCase):
    def test_version_key_non_numeric_falls_back(self) -> None:
        # Exercises the "not match" branch
        self.assertEqual(_version_key("dev"), (0, 0, 0, "dev"))

    def test_is_newer_version_numeric(self) -> None:
        self.assertTrue(_is_newer_version("0.2.0", "0.1.9"))
        self.assertFalse(_is_newer_version("0.1.9", "0.1.9"))

    def test_update_available_true(self) -> None:
        info = VersionInfo(current_version="0.1.9", latest_version="0.2.0")
        self.assertTrue(info.update_available)

    def test_update_available_false_when_equal(self) -> None:
        info = VersionInfo(current_version="0.1.9", latest_version="0.1.9")
        self.assertFalse(info.update_available)

    def test_get_current_version_package_not_found_falls_back_to_pyproject(self) -> None:
        with patch("ffmpeg4discord.versioning.metadata.version") as mock_version:
            mock_version.side_effect = __import__("importlib").metadata.PackageNotFoundError
            v = get_current_version()
        self.assertIsNotNone(v)

    def test_get_current_version_generic_exception_returns_none(self) -> None:
        with patch("ffmpeg4discord.versioning.metadata.version", side_effect=Exception("boom")):
            self.assertIsNone(get_current_version())

    def test_get_latest_pypi_version_success(self) -> None:
        # Mock urllib.request.urlopen(...) as a context manager.
        resp = MagicMock()
        resp.read.return_value = b'{"info": {"version": "9.9.9"}}'
        cm = MagicMock()
        cm.__enter__.return_value = resp
        cm.__exit__.return_value = False
        with patch("ffmpeg4discord.versioning.urllib.request.urlopen", return_value=cm):
            self.assertEqual(get_latest_pypi_version(timeout_s=0.01), "9.9.9")

    def test_get_latest_pypi_version_exception_returns_none(self) -> None:
        with patch("ffmpeg4discord.versioning.urllib.request.urlopen", side_effect=Exception("no net")):
            self.assertIsNone(get_latest_pypi_version(timeout_s=0.01))

    def test_get_version_from_pyproject_missing_file(self) -> None:
        with patch("ffmpeg4discord.versioning.Path.exists", return_value=False):
            self.assertIsNone(_get_version_from_pyproject())

    def test_get_version_from_pyproject_no_version_match(self) -> None:
        with (
            patch("ffmpeg4discord.versioning.Path.exists", return_value=True),
            patch("ffmpeg4discord.versioning.Path.read_text", return_value="[project]\nname='ffmpeg4discord'\n"),
        ):
            self.assertIsNone(_get_version_from_pyproject())

    def test_get_version_from_pyproject_exception_returns_none(self) -> None:
        # Exercises the broad exception handler in _get_version_from_pyproject
        with patch("ffmpeg4discord.versioning.Path.resolve", side_effect=Exception("boom")):
            self.assertIsNone(_get_version_from_pyproject())

    def test_check_for_update_best_effort_network_failure(self) -> None:
        with patch("ffmpeg4discord.versioning.get_latest_pypi_version", return_value=None):
            info = check_for_update(timeout_s=0.01)
        # Current version should be detectable in this repo (pyproject fallback)
        self.assertIsNotNone(info.current_version)
        self.assertIsNone(info.latest_version)
        self.assertFalse(info.update_available)


if __name__ == "__main__":
    unittest.main()
