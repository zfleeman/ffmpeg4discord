import json
import re
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import ANY, MagicMock

import pytest
from flask import Flask

import ffmpeg4discord.__main__ as mainmod
from ffmpeg4discord.twopass import EncodeResult, EncodeSettings, TwoPass
from ffmpeg4discord.versioning import VersionInfo


def result(size, commands=("ffmpeg -i file.mp4 out.mp4",)):
    """An EncodeResult for output.mp4 at `size` MiB."""
    return EncodeResult(output_filename="output.mp4", output_filesize=size, commands=list(commands))


@pytest.fixture
def twopass():
    """A stand-in TwoPass whose encode lands at 5 MiB."""
    tp = MagicMock()
    tp.run.return_value = result(5)
    return tp


@pytest.fixture
def no_cleanup(monkeypatch):
    """Record output-file deletion when a failed size attempt is retried."""
    unlink = MagicMock()
    monkeypatch.setattr(mainmod.Path, "unlink", unlink)
    return unlink


@pytest.fixture
def run_main(monkeypatch, twopass):
    """Run main() with the given command line args, without checking PyPI or encoding anything."""

    def _run(**args):
        cli_args = {
            "web": False,
            "approx": False,
            "dry_run": False,
            "filename": "file.mp4",
            "target_filesize": 10,
            "output": "",
            **args,
        }
        monkeypatch.setattr(mainmod, "check_for_update", lambda **_: VersionInfo("0.1.9", "0.1.9"))
        monkeypatch.setattr(mainmod.arguments, "get_args", lambda: cli_args)
        monkeypatch.setattr(mainmod, "TwoPass", MagicMock(return_value=twopass))
        monkeypatch.setattr(mainmod, "twopass_loop", MagicMock(return_value=result(5)))
        mainmod.main()
        return mainmod.twopass_loop

    return _run


# --- the retry loop ---


def test_twopass_loop_approx_runs_once(twopass, no_cleanup):
    twopass.run.return_value = result(15)  # over the target, but --approx accepts it
    assert mainmod.twopass_loop(twopass, EncodeSettings(target_filesize=10), approx=True).output_filesize == 15
    assert twopass.run.call_count == 1


def test_twopass_loop_retries_until_under_target(twopass, no_cleanup, capsys):
    twopass.run.side_effect = [result(15), result(9)]
    assert mainmod.twopass_loop(twopass, EncodeSettings(target_filesize=10)).output_filesize == 9
    assert twopass.run.call_count == 2
    assert "The output file size" in capsys.readouterr().out
    no_cleanup.assert_called_once()  # the oversized first output is deleted


def test_twopass_loop_cuts_target_by_min_step(twopass, no_cleanup):
    # just over the target: the size ratio alone would barely lower the bitrate
    twopass.run.side_effect = [result(8.0005), result(7.8)]
    settings = EncodeSettings(target_filesize=8)
    mainmod.twopass_loop(twopass, settings)
    retry_settings = twopass.run.call_args_list[1].args[0]
    assert retry_settings.target_filesize == pytest.approx(8 * (1 - mainmod.MIN_RETRY_STEP))
    assert settings.target_filesize == 8  # the caller's settings stay the same


def test_success_message():
    message = mainmod.success_message(result(4.567))
    assert message == f"Your compressed video file (4.57MB) is located at {Path('output.mp4').resolve()}"


# --- helpers ---


def test_open_browser(monkeypatch):
    monkeypatch.setattr(mainmod.time, "sleep", MagicMock())
    monkeypatch.setattr(mainmod.webbrowser, "open", MagicMock())
    mainmod.open_browser(1234)
    mainmod.webbrowser.open.assert_called_once_with("http://127.0.0.1:1234")


def test_twopass_loop_preserves_existing_pass_logs(tmp_path, monkeypatch, twopass):
    monkeypatch.chdir(tmp_path)
    existing_logs = ["ffmpeg2pass-0.log", "ffmpeg2pass-0.log.mbtree", "x265_2pass.log"]
    for name in existing_logs:
        (tmp_path / name).touch()

    mainmod.twopass_loop(twopass, EncodeSettings(target_filesize=10), approx=True)

    assert all((tmp_path / name).exists() for name in existing_logs)


# --- main() ---


def test_main_cli_encodes_and_prints_result(run_main, twopass, capsys):
    twopass_loop = run_main()
    twopass_loop.assert_called_once()
    out = capsys.readouterr().out
    assert "Your compressed video file (5MB)" in out
    assert "ffmpeg -i file.mp4 out.mp4" in out.splitlines()


def test_main_builds_settings_from_the_flags(run_main):
    twopass_loop = run_main(crop="0x0x640x360", start="00:00:05", output="clips", approx=True)
    mainmod.TwoPass.assert_called_once_with(Path("file.mp4").resolve())
    _, settings, approx = twopass_loop.call_args.args
    assert settings == EncodeSettings(target_filesize=10, output=Path("clips"), start="00:00:05", crop="0x0x640x360")
    assert approx is True


@pytest.mark.parametrize("approx", [False, True])
def test_main_dry_run_prints_commands_without_encoding(run_main, twopass, capsys, approx):
    twopass_loop = run_main(dry_run=True, approx=approx)
    twopass_loop.assert_not_called()
    twopass.run.assert_called_once_with(ANY, dry_run=True)
    out = capsys.readouterr().out
    assert "ffmpeg -i file.mp4 out.mp4" in out.splitlines()
    # --approx never retries, so the retry note only shows without it
    assert ("re-encodes it at a lower bitrate" in out) is not approx


def test_main_web_ignores_dry_run(run_main, monkeypatch, caplog):
    app = MagicMock()
    monkeypatch.setattr(mainmod, "Flask", MagicMock(return_value=app))
    monkeypatch.setattr(mainmod.threading, "Thread", MagicMock())
    run_main(web=True, dry_run=True, port=5000)
    assert "--dry-run is ignored with --web" in caplog.text
    app.run.assert_called_once()


def test_format_commands_for_two_passes():
    lines = mainmod.format_commands(["ffmpeg -pass 1", "ffmpeg -pass 2"]).splitlines()
    assert (
        lines[0] == "Here's what this encode looks like as plain FFmpeg commands (a two-pass encode runs FFmpeg twice):"
    )
    assert lines[1:] == ["", "ffmpeg -pass 1", "", "ffmpeg -pass 2"]


def test_format_commands_for_one_pass():
    assert (
        mainmod.format_commands(["ffmpeg"]) == "Here's what this encode looks like as a plain FFmpeg command:\n\nffmpeg"
    )


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

    cli_args = {
        "web": True,
        "approx": False,
        "dry_run": False,
        "port": 5000,
        "filename": "file.mp4",
        "target_filesize": 10,
        "output": "",
    }
    monkeypatch.setattr(mainmod, "check_for_update", lambda **_: VersionInfo("0.1.9", "0.1.9"))
    monkeypatch.setattr(mainmod.arguments, "get_args", lambda: cli_args)
    monkeypatch.setattr(mainmod, "Flask", CapturedFlask)
    monkeypatch.setattr(mainmod.threading, "Thread", MagicMock())
    monkeypatch.setattr(mainmod, "twopass_loop", MagicMock(return_value=result(5)))
    mainmod.main()
    return SimpleNamespace(client=apps[0].test_client(), twopass_loop=mainmod.twopass_loop)


def posted_settings(web) -> EncodeSettings:
    """The settings the last /encode request passed to twopass_loop."""
    return web.twopass_loop.call_args.args[1]


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
    assert b"FFmpeg command" not in response.data  # nothing has been encoded yet


def test_index_page_has_the_browser_checks(web):
    page = web.client.get("/").get_data(as_text=True)
    assert 'id="encodeForm" action="/encode" method="post" novalidate' in page
    source = json.loads(re.search(r"const SOURCE = (\{.*\});", page).group(1))
    assert source == {
        "duration": 120.0,
        "width": 1920,
        "height": 1080,
        "framerate": 30,
        "size_mib": pytest.approx(50.54, abs=0.01),
        "audio_tracks": 1,
        "audio_kbps": 128.0,
    }


def test_source_facts_without_audio(probe):
    probe["streams"].pop()
    assert mainmod.source_facts(TwoPass(Path("file.mp4")))["audio_kbps"] is None


@pytest.mark.parametrize(
    "tags",
    [
        {"side_data_list": [{"side_data_type": "Display Matrix", "rotation": -90}]},
        {"tags": {"rotate": "90"}},  # older ffmpeg builds
    ],
)
def test_source_facts_swap_the_size_of_rotated_video(probe, tags):
    probe["streams"][0].update(tags)
    facts = mainmod.source_facts(TwoPass(Path("file.mp4")))
    assert (facts["width"], facts["height"]) == (1080, 1920)


def test_encode_banner_shows_the_commands(web):
    web.twopass_loop.return_value = result(5, commands=['ffmpeg -i "a b.mp4"'])
    response = web.client.post("/encode", data=encode_form())
    assert b"Your compressed video file (5MB)" in response.data
    assert b"as a plain FFmpeg command:" in response.data
    assert b"ffmpeg -i &#34;a b.mp4&#34;" in response.data  # escaped for HTML


def test_video_route_serves_only_the_input_file(web):
    assert web.client.get("/video").data == b"video bytes"
    assert web.client.get("/static/secret.txt").status_code == 404


def test_encode_builds_settings_from_the_form(web):
    response = web.client.post("/encode", data=encode_form(framerate="30", approx="True"))
    assert response.status_code == 200

    twopass, settings, approx = web.twopass_loop.call_args.args
    assert twopass.clip_times(settings) == (10, 40)
    assert settings.target_filesize == 8
    assert settings.framerate == 30
    assert settings.audio_br == 96
    assert settings.no_audio is False
    assert settings.output == Path("out.mp4")
    assert approx is True


def test_encode_keeps_milliseconds(web):
    web.client.post("/encode", data=encode_form(startTime="10.25", endTime="40.5"))
    twopass, settings, _ = web.twopass_loop.call_args.args
    assert twopass.clip_times(settings) == (10.25, 40.5)


def test_encode_does_not_change_the_starting_form(web):
    # Each request gets its own settings, so an encode doesn't change what the page starts with.
    web.client.post("/encode", data=encode_form(crop="0x0x640x360", resolution="640x360"))
    assert posted_settings(web).crop == "0x0x640x360"
    page = web.client.get("/").data
    assert b'value="0x0x640x360"' not in page
    assert b'value="640x360"' not in page


def test_encode_unchecked_audio_means_no_audio(web):
    form = encode_form()
    del form["include_audio"]
    web.client.post("/encode", data=form)
    assert posted_settings(web).no_audio is True


@pytest.mark.parametrize(
    "amix_mode, amix, normalize",
    [("none", False, False), ("mix", True, False), ("mix_normalize", True, True)],
)
def test_encode_amix_mode(web, amix_mode, amix, normalize):
    web.client.post("/encode", data=encode_form(amix_mode=amix_mode))
    settings = posted_settings(web)
    assert (settings.amix, settings.amix_normalize) == (amix, normalize)


@pytest.mark.parametrize("astreams, expected", [(["0", "2"], [0, 2]), ([], None)])
def test_encode_audio_stream_selection(web, astreams, expected):
    web.client.post("/encode", data=encode_form(astreams=astreams))
    assert posted_settings(web).astreams == expected


# --- web UI form errors ---


@pytest.mark.parametrize(
    "overrides, message",
    [
        ({"startTime": ""}, b"must be numbers of seconds"),
        ({"endTime": "abc"}, b"must be numbers of seconds"),
        ({"startTime": "40", "endTime": "10"}, b"Start time must come before the End time"),
        ({"endTime": "500"}, b"between 0 and 120 seconds"),
        ({"target_filesize": "abc"}, b"File Size must be a number above 0"),
        ({"target_filesize": "0"}, b"File Size must be a number above 0"),
        ({"target_filesize": "nan"}, b"File Size must be a number above 0"),
        ({"target_filesize": "60"}, b"larger than the input file (50.54 MiB)"),
        ({"codec": "not_a_codec"}, b"Pick a Video Codec from the list"),
        ({"resolution": "1280"}, b"Resolution must be width x height"),
        ({"crop": "0x0x100"}, b"Crop must be four numbers joined by x"),
        ({"output": "missing/out.mp4"}, b"The output folder missing"),
        ({"framerate": "29.97"}, b"Frame Rate must be a whole number above 0"),
        ({"framerate": "0"}, b"Frame Rate must be a whole number above 0"),
        ({"audio_br": "loud"}, b"Audio Bitrate must be a number above 0"),
    ],
)
def test_encode_bad_input_shows_an_error(web, overrides, message):
    response = web.client.post("/encode", data=encode_form(**overrides))
    assert response.status_code == 400
    assert b"Nothing was encoded" in response.data
    assert message in response.data
    web.twopass_loop.assert_not_called()


def test_encode_error_keeps_what_the_user_typed(web):
    response = web.client.post("/encode", data=encode_form(startTime="12.5", crop="0x0x100", resolution="640x360"))
    assert b'value="12.5"' in response.data
    assert b'value="0x0x100"' in response.data
    assert b'value="640x360"' in response.data


def test_encode_blank_optional_fields_are_fine(web):
    response = web.client.post("/encode", data=encode_form(framerate="", audio_br="", resolution="", crop=""))
    assert response.status_code == 200
    settings = posted_settings(web)
    assert settings.framerate is None
    assert settings.audio_br is None  # TwoPass uses the input's audio bitrate


@pytest.fixture
def two_tracks(probe):
    """Add a second audio track to the probe. List it before `web` in a test so the TwoPass sees both tracks."""
    probe["streams"].append({"codec_type": "audio", "bit_rate": "128000", "index": 2})


def test_encode_two_tracks_needs_one_checked(two_tracks, web):
    response = web.client.post("/encode", data=encode_form())
    assert response.status_code == 400
    assert b"Check at least one of the Audio Streams" in response.data
    web.twopass_loop.assert_not_called()


def test_encode_two_tracks_without_audio_needs_none_checked(two_tracks, web):
    form = encode_form()
    del form["include_audio"]
    assert web.client.post("/encode", data=form).status_code == 200


def test_encode_twopass_value_error_is_shown(web):
    web.twopass_loop.side_effect = ValueError("Target file size of 8.00 MiB is too small")
    response = web.client.post("/encode", data=encode_form())
    assert response.status_code == 400
    assert b"Target file size of 8.00 MiB is too small" in response.data


def test_encode_ffmpeg_failure_points_to_the_terminal(web, caplog):
    web.twopass_loop.side_effect = RuntimeError("FFmpeg failed during the first pass.")
    response = web.client.post("/encode", data=encode_form())
    assert response.status_code == 400
    assert b"Its error message is in the terminal running ff4d" in response.data
    assert "FFmpeg failed during the first pass." in caplog.text


def test_encode_strips_quotes_from_a_pasted_output_path(web, tmp_path):
    response = web.client.post("/encode", data=encode_form(output=f'"{tmp_path}"'))
    assert response.status_code == 200
    assert posted_settings(web).output == tmp_path


def test_encode_ignores_audio_streams_that_are_not_numbers(web):
    # "²" passes str.isdigit() but int() can't read it. The bad frame rate makes the error page render too.
    response = web.client.post("/encode", data=encode_form(astreams=["²"], framerate="bad"))
    assert response.status_code == 400
