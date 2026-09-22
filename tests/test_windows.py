import importlib
import logging
import platform
import sys
import zipfile

import pytest

MODULE = "ffmpeg4discord.windows"


@pytest.fixture
def import_windows(monkeypatch, tmp_path):
    """Import windows.py as if on Windows, with Python installed at the given path inside a temp folder.

    windows.py does its setup (OS check, picking and creating the install folder) at import time,
    so each test gets a fresh import.
    """

    def _import(python_exe="Python/python.exe"):
        monkeypatch.setattr(platform, "system", lambda: "Windows")
        monkeypatch.setattr(sys, "executable", str(tmp_path / python_exe))
        monkeypatch.delitem(sys.modules, MODULE, raising=False)
        return importlib.import_module(MODULE)

    return _import


def test_exits_when_not_on_windows(monkeypatch):
    monkeypatch.setattr(platform, "system", lambda: "Linux")
    monkeypatch.delitem(sys.modules, MODULE, raising=False)
    with pytest.raises(SystemExit):
        importlib.import_module(MODULE)


def test_python_org_install_targets_scripts_folder(import_windows, tmp_path):
    windows = import_windows("Python/python.exe")
    assert windows.target == tmp_path / "Python" / "Scripts"
    assert windows.target.is_dir()


def test_microsoft_store_install_targets_windowsapps_folder(import_windows, tmp_path):
    windows = import_windows("WindowsApps/PythonSoftwareFoundation/python.exe")
    assert windows.target == tmp_path / "WindowsApps"


def test_warns_when_target_is_not_on_path(import_windows, monkeypatch, caplog):
    monkeypatch.setenv("PATH", "")
    with caplog.at_level(logging.WARNING):
        import_windows()
    assert "not in your" in caplog.text


def test_no_warning_when_target_is_on_path(import_windows, monkeypatch, tmp_path, caplog):
    monkeypatch.setenv("PATH", str(tmp_path / "Python" / "Scripts"))
    with caplog.at_level(logging.WARNING):
        import_windows()
    assert "not in your" not in caplog.text


def test_copy_directory_contents_copies_files_only(import_windows, tmp_path):
    windows = import_windows()
    source, dest = tmp_path / "source", tmp_path / "dest"
    (source / "subfolder").mkdir(parents=True)
    (source / "ffmpeg.exe").write_text("binary")
    dest.mkdir()

    windows.copy_directory_contents(source, dest)

    assert [p.name for p in dest.iterdir()] == ["ffmpeg.exe"]


def test_download_with_progress(import_windows, monkeypatch, tmp_path, capsys):
    windows = import_windows()

    def fake_urlretrieve(url, save_path, reporthook):
        reporthook(1, 512 * 1024, 1024 * 1024)  # half of a 1 MB download
        open(save_path, "wb").close()

    monkeypatch.setattr(windows, "urlretrieve", fake_urlretrieve)
    save_path = tmp_path / "new_folder" / "ffmpeg.zip"
    windows.download_with_progress("https://example.com/ffmpeg.zip", str(save_path))

    assert save_path.exists()
    assert "(50.0%)" in capsys.readouterr().out


def test_install_unzips_and_copies_ffmpeg(import_windows, monkeypatch, tmp_path):
    windows = import_windows()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(windows, "download_with_progress", lambda url, save_path: None)

    # stand-in for the download: one top-level folder with the executables in bin/, like the real zip
    (tmp_path / "ffmpeg").mkdir()
    with zipfile.ZipFile("ffmpeg/ffmpeg.zip", "w") as zf:
        zf.writestr("ffmpeg-7.1-essentials_build/", "")
        zf.writestr("ffmpeg-7.1-essentials_build/bin/ffmpeg.exe", "binary")

    windows.install()

    assert (windows.target / "ffmpeg.exe").read_text() == "binary"
    assert not (tmp_path / "ffmpeg").exists()  # the download folder is cleaned up
