from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from flask import Flask

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
    mainmod.webbrowser.open.assert_called_once_with("http://127.0.0.1:1234")


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
    app.run.assert_called_once_with("127.0.0.1", port=5000)


# --- web UI routes ---


@pytest.fixture
def web(monkeypatch, probe, tmp_path):
    """Run main() in web mode with a real TwoPass, then return a Flask test client instead of starting a server."""
    apps = []
    monkeypatch.chdir(tmp_path)
    (tmp_path / "file.mp4").write_bytes(b"video bytes")
    (tmp_path / "secret.txt").write_text("not for the browser")

    class CapturedFlask(Flask):
        def run(self, *args, **kwargs):
            apps.append(self)

    cli_args = {"web": True, "approx": False, "port": 5000, "filename": "file.mp4", "target_filesize": 10}
    monkeypatch.setattr(mainmod, "check_for_update", lambda **_: VersionInfo("0.1.9", "0.1.9"))
    monkeypatch.setattr(mainmod.arguments, "get_args", lambda: cli_args)
    monkeypatch.setattr(mainmod, "Flask", CapturedFlask)
    monkeypatch.setattr(mainmod.threading, "Thread", MagicMock())
    monkeypatch.setattr(mainmod, "twopass_loop", MagicMock())
    mainmod.main()
    return SimpleNamespace(client=apps[0].test_client(), twopass_loop=mainmod.twopass_loop)


def encode_form(**overrides):
    """The form the web UI posts to /encode, with the values a user would leave in place."""
    form = {
        "startTime": "10",
        "endTime": "40",
        "target_filesize": "8",
        "resolution": "",
        "crop": "",
        "output": "out.mp4",
        "codec": "x264",
        "framerate": "",
        "audio_br": "96",
        "include_audio": "True",
        "amix_mode": "none",
    }
    return {**form, **overrides}


def test_index_page_renders(web):
    response = web.client.get("/")
    assert response.status_code == 200
    assert b"ffmpeg4discord v0.1.9" in response.data
    assert b'src="/video"' in response.data


def test_video_route_serves_only_the_input_file(web):
    assert web.client.get("/video").data == b"video bytes"
    assert web.client.get("/static/secret.txt").status_code == 404


def test_encode_applies_the_form_to_twopass(web):
    response = web.client.post("/encode", data=encode_form(framerate="30", approx="True"))
    assert response.status_code == 200

    kwargs = web.twopass_loop.call_args.kwargs
    tp = kwargs["twopass"]
    assert tp.times == {"ss": "00:00:10", "to": "00:00:40"}
    assert tp.length == 30
    assert tp.target_filesize == 8
    assert tp.framerate == 30
    assert tp.audio_br == 96000
    assert tp.no_audio is False
    assert kwargs == {"twopass": tp, "target_filesize": 8, "approx": True}


def test_encode_unchecked_audio_means_no_audio(web):
    form = encode_form()
    del form["include_audio"]
    web.client.post("/encode", data=form)
    assert web.twopass_loop.call_args.kwargs["twopass"].no_audio is True


@pytest.mark.parametrize(
    "amix_mode, amix, normalize",
    [("none", False, False), ("mix", True, False), ("mix_normalize", True, True)],
)
def test_encode_amix_mode(web, amix_mode, amix, normalize):
    web.client.post("/encode", data=encode_form(amix_mode=amix_mode))
    tp = web.twopass_loop.call_args.kwargs["twopass"]
    assert (tp.amix, tp.amix_normalize) == (amix, normalize)


@pytest.mark.parametrize("astreams, expected", [(["0", "2"], [0, 2]), ([], None)])
def test_encode_audio_stream_selection(web, astreams, expected):
    web.client.post("/encode", data=encode_form(astreams=astreams))
    assert web.twopass_loop.call_args.kwargs["twopass"].astreams == expected
