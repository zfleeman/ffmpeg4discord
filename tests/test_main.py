from unittest.mock import MagicMock

import pytest

import ffmpeg4discord.__main__ as mainmod
from ffmpeg4discord.versioning import VersionInfo


@pytest.fixture
def twopass():
    """A stand-in TwoPass whose encode lands at 5 MiB."""
    tp = MagicMock()
    tp.codec = "x264"
    tp.run.return_value = 5
    tp.output_filesize = 5
    tp.output_filename = "output.mp4"
    tp.target_filesize = 10
    tp.message = ""
    return tp


@pytest.fixture
def no_cleanup(monkeypatch):
    """Stop twopass_loop from deleting files. Returns the mock that replaces `Path.unlink`."""
    unlink = MagicMock()
    monkeypatch.setattr(mainmod, "cleanup_files", MagicMock())
    monkeypatch.setattr(mainmod.Path, "unlink", unlink)
    return unlink


@pytest.fixture
def run_main(monkeypatch, twopass):
    """Run main() with the given command line args, without checking PyPI or encoding anything."""

    def _run(**args):
        cli_args = {"web": False, "approx": False, "filename": "file.mp4", **args}
        monkeypatch.setattr(mainmod, "check_for_update", lambda **_: VersionInfo("0.1.9", "0.1.9"))
        monkeypatch.setattr(mainmod.arguments, "get_args", lambda: cli_args)
        monkeypatch.setattr(mainmod, "TwoPass", MagicMock(return_value=twopass))
        monkeypatch.setattr(mainmod, "twopass_loop", MagicMock())
        mainmod.main()
        return mainmod.twopass_loop

    return _run


# --- the retry loop ---


def test_twopass_loop_approx_runs_once(twopass, no_cleanup):
    twopass.run.return_value = 15  # over the target, but --approx accepts it
    mainmod.twopass_loop(twopass, target_filesize=10, approx=True)
    assert twopass.run.call_count == 1
    assert "Your compressed video file" in twopass.message


def test_twopass_loop_retries_until_under_target(twopass, no_cleanup, capsys):
    twopass.run.side_effect = [15, 9]
    mainmod.twopass_loop(twopass, target_filesize=10)
    assert twopass.run.call_count == 2
    assert "The output file size" in capsys.readouterr().out
    no_cleanup.assert_called_once()  # the oversized first output is deleted
    assert "Your compressed video file" in twopass.message


def test_twopass_loop_cuts_target_by_min_step(twopass, no_cleanup):
    # just over the target: the size ratio alone would barely lower the bitrate
    twopass.run.side_effect = [8.0005, 7.8]
    twopass.target_filesize = 8
    mainmod.twopass_loop(twopass, target_filesize=8)
    assert twopass.target_filesize == pytest.approx(8 * (1 - mainmod.MIN_RETRY_STEP))


# --- helpers ---


def test_open_browser(monkeypatch):
    monkeypatch.setattr(mainmod.time, "sleep", MagicMock())
    monkeypatch.setattr(mainmod.webbrowser, "open", MagicMock())
    mainmod.open_browser(1234)
    mainmod.webbrowser.open.assert_called_once_with("http://localhost:1234")


def test_cleanup_files(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    for name in ("ffmpeg2pass-0.log", "ffmpeg2pass-0.log.mbtree", "keep.mp4"):
        (tmp_path / name).touch()
    mainmod.cleanup_files("ffmpeg2pass*")
    assert [p.name for p in tmp_path.iterdir()] == ["keep.mp4"]


# --- main() ---


def test_main_cli_encodes_and_prints_result(run_main, twopass, capsys):
    twopass.message = "done"
    twopass_loop = run_main()
    twopass_loop.assert_called_once()
    assert "done" in capsys.readouterr().out.splitlines()


def test_main_web_starts_flask_on_port(run_main, monkeypatch):
    app = MagicMock()
    monkeypatch.setattr(mainmod, "Flask", MagicMock(return_value=app))
    monkeypatch.setattr(mainmod.threading, "Thread", MagicMock())
    run_main(web=True, approx=True, port=5000)
    mainmod.threading.Thread.assert_called_once()
    app.run.assert_called_once_with("0.0.0.0", port=5000)
