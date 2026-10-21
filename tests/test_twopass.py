import logging
import shlex
import shutil
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import ffmpeg
import pytest

from ffmpeg4discord.__main__ import twopass_loop
from ffmpeg4discord.twopass import (
    CODEC_ENCODERS,
    CODEC_OVERRIDES,
    EncodeSettings,
    TwoPass,
    available_codecs,
    command_for_display,
    fps_mode_flag,
    run_pass,
    seconds_from_ts_string,
    seconds_to_timestamp,
    timestamp_from_percentage,
    tonemap_filters,
)


@pytest.fixture
def make_twopass(probe):
    """Build a TwoPass from the fake probe."""

    def _make(filename="test.mp4"):
        return TwoPass(Path(filename))

    return _make


def make_settings(**kwargs) -> EncodeSettings:
    """Settings for a 10 MiB encode to output.mp4. Keyword arguments override the defaults."""
    return EncodeSettings(**{"target_filesize": 10, "output": Path("output.mp4"), **kwargs})


# lets tests call _generate_params() without going through run()
BITRATE = {"b:v": 1000000}


@pytest.fixture
def passes(monkeypatch):
    """Record each ffmpeg pass instead of running it. Every output file reports a size of 10 MiB."""
    calls = []

    def fake_run_pass(ffoutput, pass_name, hint="", **run_kwargs):
        args = [str(arg) for arg in ffoutput.compile()]
        calls.append(SimpleNamespace(name=pass_name, args=args, run_kwargs=run_kwargs))
        return (b"", b"")

    monkeypatch.setattr("ffmpeg4discord.twopass.run_pass", fake_run_pass)
    monkeypatch.setattr("ffmpeg4discord.twopass.os.path.getsize", lambda _: 10 * 1024 * 1024)
    return calls


# --- timestamp helpers ---

TIMESTAMPS = [("01:02:03", 3723), ("00:00:00", 0), ("10:00:00", 36000), ("00:01:30.250", 90.25)]


@pytest.mark.parametrize("timestamp, seconds", TIMESTAMPS)
def test_seconds_from_ts_string(timestamp, seconds):
    assert seconds_from_ts_string(timestamp) == seconds


@pytest.mark.parametrize(
    "timestamp, seconds",
    [("1:30", 90), ("01:30.5", 90.5), ("90", 90), ("90.25", 90.25), ("5.750", 5.75), ("1:02:03.004", 3723.004)],
)
def test_seconds_from_ts_string_short_forms(timestamp, seconds):
    assert seconds_from_ts_string(timestamp) == pytest.approx(seconds)


@pytest.mark.parametrize("timestamp", ["", "abc", "1:2:3:4", "-5", "00:-1:00", "1::2", "inf", "nan"])
def test_seconds_from_ts_string_invalid(timestamp):
    with pytest.raises(ValueError, match="Invalid time"):
        seconds_from_ts_string(timestamp)


@pytest.mark.parametrize(
    "seconds, timestamp", [(5.75, "00:00:05.750"), (1.9999999, "00:00:02"), (0.001, "00:00:00.001")]
)
def test_seconds_to_timestamp_milliseconds(seconds, timestamp):
    assert seconds_to_timestamp(seconds) == timestamp


@pytest.mark.parametrize("timestamp, seconds", TIMESTAMPS)
def test_seconds_to_timestamp(timestamp, seconds):
    assert seconds_to_timestamp(seconds) == timestamp


@pytest.mark.parametrize(
    "value, duration, expected",
    [
        ("75%", 60, "00:00:45"),
        ("0%", 60, "00:00:00"),
        ("100%", 60, "00:01:00"),
        ("33.3%", 100, "00:00:33.300"),
        ("00:00:10", 60, "00:00:10"),  # timestamps pass through unchanged
    ],
)
def test_timestamp_from_percentage(value, duration, expected):
    assert timestamp_from_percentage(value, duration) == expected


@pytest.mark.parametrize("value", ["abc%", "150%", "-5%"])
def test_timestamp_from_percentage_invalid(value):
    with pytest.raises(ValueError):
        timestamp_from_percentage(value, 60)


# --- reading the probe and trim times ---


def test_probe_values_are_read(make_twopass):
    tp = make_twopass()
    assert tp.duration == 120
    assert tp.ratio == pytest.approx(1920 / 1080)
    assert tp.init_framerate == 30
    assert tp.source_audio_br == 128000
    assert tp.input_filesize == pytest.approx(50.54, abs=0.01)


def test_fractional_duration_is_kept(probe, make_twopass):
    # rounding 5.9 s down to 5 would budget about 18% too much bitrate
    probe["format"]["duration"] = "5.9"
    assert make_twopass().clip_times(make_settings()) == (0, 5.9)


def test_audio_br_is_converted_to_bps(make_twopass):
    assert make_twopass()._audio_bitrate(make_settings(audio_br=96)) == 96000


def test_audio_br_defaults_to_the_source_bitrate(make_twopass):
    assert make_twopass()._audio_bitrate(make_settings()) == 128000


def test_warns_when_no_audio_stream(probe, make_twopass, caplog):
    probe["streams"].pop()
    make_twopass()
    assert "no audio stream found" in caplog.text.lower()


@pytest.mark.parametrize(
    "times, ss, to",
    [
        ({"start": "00:00:10", "end": "00:01:00"}, "00:00:10", "00:01:00"),
        ({"end": "00:01:00"}, "00:00:00", "00:01:00"),
        ({"start": "00:00:10"}, "00:00:10", "00:02:00"),
        ({}, "00:00:00", "00:02:00"),
        ({"start": "50%", "end": "75%"}, "00:01:00", "00:01:30"),
        ({"start": "00:00:30", "end": "50%"}, "00:00:30", "00:01:00"),
        ({"start": "1:05.5", "end": "90.25"}, "00:01:05.500", "00:01:30.250"),
    ],
)
def test_trim_times(make_twopass, times, ss, to):
    start, end = make_twopass().clip_times(make_settings(**times))
    assert (seconds_to_timestamp(start), seconds_to_timestamp(end)) == (ss, to)


@pytest.mark.parametrize(
    "filename, start, end",
    [
        ("000010-000030.mp4", 10, 30),
        ("000010.mp4", 10, 120),
        ("badname.mp4", 0, 120),  # falls back to the whole video
    ],
)
def test_trim_times_from_filename(make_twopass, filename, start, end):
    assert make_twopass(filename).clip_times(make_settings(filename_times=True)) == (start, end)


def test_invalid_filename_times_warn(make_twopass, caplog):
    make_twopass("badname.mp4").clip_times(make_settings(filename_times=True))
    assert "invalid time format" in caplog.text.lower()


@pytest.mark.parametrize("start, end", [("00:02:00", "00:01:00"), ("00:01:00", "00:01:00")])
def test_end_not_after_start_raises(make_twopass, start, end):
    with pytest.raises(ValueError, match="Time Paradox"):
        make_twopass().clip_times(make_settings(start=start, end=end))


def test_target_larger_than_input_raises(make_twopass):
    # the fake input is 53,000,000 bytes, about 50.5 MiB
    with pytest.raises(ValueError, match="larger than the input file"):
        make_twopass().run(make_settings(target_filesize=51), dry_run=True)


# --- bitrate budget ---


def test_bitrate_targets(make_twopass):
    # 10 MiB over 100 seconds is 819.2 kbps total. Minus 128 kbps audio leaves 691 kbps for video.
    assert make_twopass()._bitrate_targets(make_settings(), 100) == {
        "b:v": 691000,
        "minrate": 691000 * 0.5,
        "maxrate": 691000 * 1.45,
        "bufsize": 691000 * 2,
    }


def test_bitrate_targets_raise_when_audio_uses_whole_budget(make_twopass):
    # 20 MiB over 30 minutes is ~91 kbps total, less than the 96 kbps audio track.
    with pytest.raises(ValueError, match="no bitrate left for video"):
        make_twopass()._bitrate_targets(make_settings(target_filesize=20, audio_br=96), 1800)


def test_bitrate_targets_ignore_audio_when_no_audio(make_twopass):
    # Same budget as above, but without audio the whole ~91 kbps goes to video.
    targets = make_twopass()._bitrate_targets(make_settings(target_filesize=20, audio_br=96, no_audio=True), 1800)
    assert targets["b:v"] == 91000


def test_bitrate_targets_ignore_audio_without_an_audio_stream(probe, make_twopass):
    probe["streams"].pop()
    targets = make_twopass()._bitrate_targets(make_settings(target_filesize=20, audio_br=96), 1800)
    assert targets["b:v"] == 91000


# --- ffmpeg parameters ---


def test_generate_params_x264(make_twopass):
    params = make_twopass()._generate_params(make_settings(), BITRATE)
    assert params["pass1"]["c:v"] == "libx264"
    assert params["pass2"]["c:v"] == "libx264"
    assert params["pass2"]["c:a"] == "aac"
    assert params["pass2"]["b:v"] == 1000000


def test_generate_params_vp9(make_twopass):
    params = make_twopass()._generate_params(make_settings(codec="vp9"), BITRATE)
    assert params["pass2"]["c:a"] == "libopus"
    assert params["pass2"]["row-mt"] == 1
    assert params["pass2"]["cpu-used"] == 5
    assert params["pass2"]["deadline"] == "good"


def test_generate_params_x265_uses_x265_params(make_twopass):
    # x265 takes its pass number through -x265-params instead of -pass
    params = make_twopass()._generate_params(make_settings(codec="x265"), BITRATE)
    assert "pass" not in params["pass1"]
    assert "pass" not in params["pass2"]
    assert params["pass1"]["x265-params"] == "pass=1"
    assert params["pass2"]["x265-params"] == "pass=2"
    assert params["pass2"]["c:v"] == "libx265"


def test_generate_params_hardware_codec_has_no_pass_flags(make_twopass):
    params = make_twopass()._generate_params(make_settings(codec="h264_videotoolbox"), BITRATE)
    assert "pass" not in params["pass1"]
    assert "pass" not in params["pass2"]
    assert params["pass2"]["c:v"] == "h264_videotoolbox"
    assert params["pass2"]["c:a"] == "aac"


def test_generate_params_applies_shared_overrides_to_both_passes(make_twopass, monkeypatch):
    # No built-in codec uses a "both" section yet, so add one for this test.
    monkeypatch.setitem(CODEC_OVERRIDES, "x264", {"both": {"preset": "slow"}})
    params = make_twopass()._generate_params(make_settings(), BITRATE)
    assert params["pass1"]["preset"] == "slow"
    assert params["pass2"]["preset"] == "slow"


@pytest.mark.parametrize("codec", CODEC_ENCODERS)
def test_generate_params_forces_yuv420p(make_twopass, codec):
    """10-bit and 4:4:4 sources must be converted to 8-bit 4:2:0 so the output plays everywhere."""
    params = make_twopass()._generate_params(make_settings(codec=codec), BITRATE)
    assert params["pass1"]["pix_fmt"] == "yuv420p"
    assert params["pass2"]["pix_fmt"] == "yuv420p"


def test_generate_params_lowers_framerate(make_twopass):
    params = make_twopass()._generate_params(make_settings(framerate=15), BITRATE)
    assert params["pass1"]["r"] == 15
    assert params["pass2"]["r"] == 15


def test_generate_params_keeps_source_framerate_when_asked_for_more(make_twopass, caplog):
    params = make_twopass()._generate_params(make_settings(framerate=60), BITRATE)
    assert "r" not in params["pass1"]
    assert "r" not in params["pass2"]
    assert "desired framerate" in caplog.text.lower()


# --- filters ---


def test_apply_video_filters_crop_and_resolution(make_twopass):
    video = MagicMock()
    video.crop.return_value = video
    video.filter.return_value = video
    make_twopass()._apply_video_filters(video, make_settings(crop="10x20x640x360", resolution="1280x720"))
    video.crop.assert_called_once_with(x="10", y="20", width="640", height="360")
    video.filter.assert_called_once_with("scale", "1280x720")


def test_apply_video_filters_warns_on_aspect_ratio_mismatch(make_twopass, caplog):
    # the source is 16:9 and 1280x800 is 16:10
    video = MagicMock()
    video.filter.return_value = video
    make_twopass()._apply_video_filters(video, make_settings(resolution="1280x800"))
    assert "aspect ratio does not match" in caplog.text.lower()


def test_crop_does_not_change_the_next_encodes_aspect_ratio(make_twopass, caplog):
    # A 4:3 crop once overwrote the source's ratio, so a later 16:9 resize without a crop warned.
    tp = make_twopass()
    video = MagicMock()
    video.crop.return_value = video
    video.filter.return_value = video
    tp._apply_video_filters(video, make_settings(crop="0x0x1440x1080"))
    tp._apply_video_filters(video, make_settings(resolution="1280x720"))
    assert "aspect ratio does not match" not in caplog.text.lower()
    assert tp.ratio == pytest.approx(1920 / 1080)


@pytest.mark.parametrize("astreams, expected", [(None, "a:0"), ([1, 0], "a:1"), ([5, 1], "a:1")])
def test_apply_audio_filters_without_mixing_keeps_one_track(probe, make_twopass, astreams, expected):
    # two audio tracks, like ShadowPlay with a separate mic track; only one fits the bitrate budget
    probe["streams"].append({"codec_type": "audio", "bit_rate": "128000", "index": 2})
    audio = make_twopass()._apply_audio_filters(ffmpeg.input("test.mp4"), make_settings(astreams=astreams))
    assert audio.selector == expected


def test_apply_audio_filters_mixes_selected_tracks(probe, make_twopass):
    # three audio tracks; 5 is out of range and gets dropped
    for index in (2, 3):
        probe["streams"].append({"codec_type": "audio", "bit_rate": "128000", "index": index})
    settings = make_settings(amix=True, astreams=[0, 2, 5])
    audio = make_twopass()._apply_audio_filters(ffmpeg.input("test.mp4"), settings)
    assert audio.node.name == "amix"
    assert audio.node.kwargs == {"normalize": 0, "inputs": 2}
    assert [edge.upstream_selector for edge in audio.node.incoming_edges] == ["a:0", "a:2"]


def test_apply_audio_filters_mixes_all_tracks_when_none_selected(probe, make_twopass):
    probe["streams"].append({"codec_type": "audio", "bit_rate": "128000", "index": 2})
    settings = make_settings(amix=True, astreams=None, amix_normalize=True)
    audio = make_twopass()._apply_audio_filters(ffmpeg.input("test.mp4"), settings)
    assert audio.node.name == "amix"
    assert audio.node.kwargs == {"normalize": 1, "inputs": 2}
    assert [edge.upstream_selector for edge in audio.node.incoming_edges] == ["a:0", "a:1"]


def test_apply_audio_filters_empty_selection_returns_none(make_twopass):
    settings = make_settings(amix=True, astreams=[])
    assert make_twopass()._apply_audio_filters(ffmpeg.input("test.mp4"), settings) is None


# --- running the encode ---


def test_run_returns_output_size(make_twopass, passes):
    assert make_twopass().run(make_settings(verbose=True)).output_filesize == pytest.approx(10, abs=0.01)


def test_run_two_passes_with_audio(make_twopass, passes):
    result = make_twopass().run(make_settings())
    first, second = passes
    assert (first.name, second.name) == ("first", "second")
    assert "pipe:" in first.args
    assert first.run_kwargs == {"capture_stdout": True}
    assert result.output_filename in second.args
    assert "0:a:0" in second.args
    assert second.run_kwargs == {"overwrite_output": True}


def test_run_without_audio_stream_outputs_video_only(probe, make_twopass, passes):
    probe["streams"].pop()
    make_twopass().run(make_settings(audio_br=96))
    assert "0:a:0" not in passes[-1].args


def test_run_no_audio_flag_omits_audio(make_twopass, passes):
    make_twopass().run(make_settings(no_audio=True))
    assert "0:a:0" not in passes[-1].args


def test_run_hardware_codec_skips_first_pass(make_twopass, passes):
    make_twopass().run(make_settings(codec="hevc_videotoolbox"))
    assert [p.name for p in passes] == ["single"]
    assert "pipe:" not in passes[0].args


@pytest.mark.parametrize(
    "output, codec, suffix",
    [
        ("output.txt", "x264", ".mp4"),
        ("output.webm", "x264", ".mp4"),
        ("output.mp4", "vp9-speed", ".webm"),
    ],
)
def test_run_fixes_output_suffix_for_codec(make_twopass, passes, caplog, output, codec, suffix):
    result = make_twopass().run(make_settings(output=Path(output), codec=codec))
    assert result.output_filename.endswith(suffix)
    assert "output file name ends with" in caplog.text.lower()


def test_run_output_directory_gets_generated_filename(make_twopass, passes, tmp_path):
    result = make_twopass().run(make_settings(output=tmp_path))
    output = Path(result.output_filename)
    assert output.parent == tmp_path.resolve()
    assert output.name.startswith("small_")


# --- two-pass stats files (issue #89) ---


def without_pass_log(args: list[str]) -> list[str]:
    """`args` without "-passlogfile <path>"."""
    i = args.index("-passlogfile")
    return args[:i] + args[i + 2 :]


def test_run_keeps_pass_stats_in_a_temp_folder(make_twopass, passes, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    make_twopass().run(make_settings())
    first_log = passes[0].args[passes[0].args.index("-passlogfile") + 1]
    second_log = passes[1].args[passes[1].args.index("-passlogfile") + 1]
    # the second pass reads the stats the first pass wrote
    assert first_log == second_log
    assert Path(first_log).name == "ffmpeg2pass"
    assert Path(first_log).parent.name.startswith("ff4d-")
    assert Path(first_log).parent != tmp_path
    # the folder is deleted once the encode is done
    assert not Path(first_log).parent.exists()


def test_each_run_gets_its_own_stats_folder(make_twopass, passes):
    tp = make_twopass()
    tp.run(make_settings())
    tp.run(make_settings())
    folders = {Path(p.args[p.args.index("-passlogfile") + 1]).parent for p in passes}
    assert len(folders) == 2


def test_stats_folder_is_deleted_when_ffmpeg_fails(make_twopass, monkeypatch):
    folders = []

    def failing_pass(ffoutput, pass_name, hint="", **run_kwargs):
        args = [str(arg) for arg in ffoutput.compile()]
        folders.append(Path(args[args.index("-passlogfile") + 1]).parent)
        raise RuntimeError("ffmpeg failed")

    monkeypatch.setattr("ffmpeg4discord.twopass.run_pass", failing_pass)
    with pytest.raises(RuntimeError):
        make_twopass().run(make_settings())
    assert not folders[0].exists()


def test_x265_keeps_its_stats_in_x265_params(make_twopass, passes):
    make_twopass().run(make_settings(codec="x265"))
    first = passes[0].args[passes[0].args.index("-x265-params") + 1]
    second = passes[1].args[passes[1].args.index("-x265-params") + 1]
    assert first.startswith("pass=1:stats=") and second.startswith("pass=2:stats=")
    assert first.split(":stats=")[1] == second.split(":stats=")[1]
    assert first.endswith("x265_2pass.log")
    assert "-passlogfile" not in passes[0].args  # x265 ignores it


def test_x265_stats_path_escapes_ffmpeg_separators():
    # A Windows drive letter's colon would otherwise split x265-params, and a quote in a user name would start a string.
    params = TwoPass._with_pass_log({"x265-params": "pass=1"}, "x265", "C:/Users/O'Brien/Temp/ff4d-abc")
    assert params["x265-params"] == r"pass=1:stats=C\:/Users/O\'Brien/Temp/ff4d-abc/x265_2pass.log"


def test_hardware_codecs_have_no_stats_file(make_twopass, passes):
    make_twopass().run(make_settings(codec="h264_nvenc"))
    assert "-passlogfile" not in passes[0].args


def test_shown_commands_leave_out_the_temp_stats_folder(make_twopass, passes):
    for codec in ["x264", "x265"]:
        commands = make_twopass().run(make_settings(codec=codec)).commands
        assert all("ff4d-" not in command and "passlogfile" not in command for command in commands)


# --- showing the ffmpeg commands (issue #92) ---


def test_run_saves_the_commands_it_ran(make_twopass, passes, monkeypatch):
    monkeypatch.setattr("ffmpeg4discord.twopass.sys.platform", "linux")
    result = make_twopass().run(make_settings())
    first, second = (shlex.split(command) for command in result.commands)
    # the same arguments ff4d ran, minus the temp stats file, "-loglevel error -stats" at the end,
    # and with pass 1's pipe: swapped out
    assert first == [*without_pass_log(passes[0].args)[:-4], "/dev/null"]
    assert second == without_pass_log(passes[1].args)[:-3]


def test_run_hardware_codec_saves_one_command(make_twopass, passes):
    assert len(make_twopass().run(make_settings(codec="h264_nvenc")).commands) == 1


def test_dry_run_saves_commands_without_running_ffmpeg(make_twopass, passes):
    result = make_twopass().run(make_settings(), dry_run=True)
    assert result.output_filesize == 0
    assert passes == []
    assert len(result.commands) == 2


def test_one_twopass_runs_encodes_with_different_settings(make_twopass, passes):
    # The web UI reuses one TwoPass for every encode, so a setting must not leak into the next one.
    tp = make_twopass()
    cropped = tp.run(make_settings(crop="0x0x640x360", codec="vp9"), dry_run=True)
    plain = tp.run(make_settings(), dry_run=True)
    assert "crop" in cropped.commands[0] and "libvpx-vp9" in cropped.commands[0]
    assert "crop" not in plain.commands[0] and "libx264" in plain.commands[0]


@pytest.mark.parametrize(
    "platform, expected",
    [
        (
            "darwin",
            "ffmpeg -i 'C:\\Videos\\my clip.mp4' -filter_complex '[0]scale=1280:-2[s0]' -map '[s0]' "
            "-f null -metadata 'title=\"x\"' /dev/null",
        ),
        (
            "win32",
            'ffmpeg -i "C:\\Videos\\my clip.mp4" -filter_complex "[0]scale=1280:-2[s0]" -map "[s0]" '
            '-f null -metadata "title=\\"x\\"" NUL',
        ),
    ],
)
def test_command_for_display_quotes_for_the_platform(monkeypatch, platform, expected):
    monkeypatch.setattr("ffmpeg4discord.twopass.sys.platform", platform)
    ffoutput = (
        ffmpeg.input("C:\\Videos\\my clip.mp4")
        .filter("scale", 1280, -2)
        .output("pipe:", f="null", metadata='title="x"')
    )
    assert command_for_display(ffoutput) == expected


# --- ffmpeg version detection (issue #66) ---


@pytest.mark.parametrize(
    "version, flag",
    [
        ("9.0.1", "fps_mode"),
        ("5.0.1", "fps_mode"),
        ("n7.1", "fps_mode"),  # Arch and some other distros prefix an "n"
        ("4.4.2-0ubuntu0.22.04.1", "vsync"),
        ("n4.4", "vsync"),
        ("N-119043-g1234567", "fps_mode"),  # nightly builds have no number and are always newer than 5.0
    ],
)
def test_fps_mode_flag(version, flag):
    assert fps_mode_flag({"program_version": {"version": version}}) == flag


def test_fps_mode_flag_without_version_section():
    assert fps_mode_flag({}) == "fps_mode"


def test_generate_params_uses_the_detected_flag(probe, make_twopass):
    """The detected flag has to reach the actual first-pass parameters, which is what broke in #66."""
    probe["program_version"]["version"] = "4.4.2"
    params = make_twopass()._generate_params(make_settings(), BITRATE)
    assert params["pass1"]["vsync"] == "cfr"
    assert "fps_mode" not in params["pass1"]


def test_probe_requests_the_version_section(probe, monkeypatch):
    """Without this kwarg the probe output has no version to read."""
    mock_probe = MagicMock(return_value=probe)
    monkeypatch.setattr("ffmpeg4discord.twopass.ffmpeg.probe", mock_probe)
    TwoPass(Path("test.mp4"))
    assert "show_program_version" in mock_probe.call_args.kwargs


# --- codec list ---


def test_available_codecs_lists_videotoolbox_on_macos(monkeypatch):
    monkeypatch.setattr("ffmpeg4discord.twopass.sys.platform", "darwin")
    assert "h264_videotoolbox" in available_codecs()


def test_available_codecs_hides_videotoolbox_off_macos(monkeypatch):
    monkeypatch.setattr("ffmpeg4discord.twopass.sys.platform", "linux")
    codecs = available_codecs()
    assert "h264_videotoolbox" not in codecs
    assert "hevc_videotoolbox" not in codecs
    assert "h264_nvenc" in codecs


# --- run_pass error handling ---


def test_run_pass_returns_ffmpeg_output_and_forwards_kwargs():
    ffoutput = MagicMock()
    ffoutput.run.return_value = (b"out", b"err")
    assert run_pass(ffoutput, "first", capture_stdout=True) == (b"out", b"err")
    ffoutput.run.assert_called_once_with(capture_stdout=True)


def test_run_pass_turns_ffmpeg_error_into_readable_error():
    ffoutput = MagicMock()
    ffoutput.run.side_effect = ffmpeg.Error("ffmpeg", b"", b"")
    # compile() mixes strings and Path objects, which is why run_pass stringifies each argument.
    ffoutput.compile.return_value = ["ffmpeg", "-i", Path("in.mp4"), "out.mp4"]

    with pytest.raises(RuntimeError) as excinfo:
        run_pass(ffoutput, "second", overwrite_output=True)

    assert "second pass" in str(excinfo.value)
    assert "ffmpeg -i in.mp4 out.mp4" in str(excinfo.value)
    assert isinstance(excinfo.value.__cause__, ffmpeg.Error)


def test_run_pass_adds_hint_to_error():
    ffoutput = MagicMock()
    ffoutput.run.side_effect = ffmpeg.Error("ffmpeg", b"", b"")
    ffoutput.compile.return_value = ["ffmpeg"]
    with pytest.raises(RuntimeError, match="try x264"):
        run_pass(ffoutput, "single", hint="try x264")


# --- HDR tone mapping (issue #77) ---


def test_tonemap_prefers_zscale_when_built_with_libzimg(probe):
    probe["program_version"].update(version="7.1", configuration="--enable-gpl --enable-libzimg")
    chain = tonemap_filters(probe)
    assert [name for name, _ in chain] == ["zscale", "format", "zscale", "tonemap", "zscale"]


@pytest.mark.parametrize("version", ["8.1.2", "N-119043-g1234567"])
def test_tonemap_falls_back_to_scale_on_ffmpeg_8(probe, version):
    probe["program_version"]["version"] = version
    chain = tonemap_filters(probe)
    assert [name for name, _ in chain] == ["scale", "format", "tonemap", "scale"]


def test_tonemap_unavailable_on_old_ffmpeg_without_zscale(probe):
    probe["program_version"]["version"] = "7.1"
    assert tonemap_filters(probe) is None


@pytest.mark.parametrize("transfer", ["smpte2084", "arib-std-b67"])
def test_hdr_source_is_tone_mapped_and_tagged_bt709(probe, make_twopass, transfer):
    probe["program_version"]["version"] = "8.1.2"
    probe["streams"][0]["color_transfer"] = transfer
    tp = make_twopass()
    assert tp.tonemap is not None

    params = tp._generate_params(make_settings(), BITRATE)
    assert params["pass2"]["color_trc"] == "bt709"
    assert params["pass2"]["colorspace"] == "bt709"

    video = MagicMock()
    video.filter.return_value = video
    tp._apply_video_filters(video, make_settings())
    assert "tonemap" in [c.args[0] for c in video.filter.call_args_list]


def test_sdr_source_is_left_alone(probe, make_twopass):
    probe["program_version"]["version"] = "8.1.2"
    probe["streams"][0]["color_transfer"] = "bt709"
    tp = make_twopass()
    assert tp.tonemap is None
    assert "color_trc" not in tp._generate_params(make_settings(), BITRATE)["pass2"]


def test_hdr_on_old_ffmpeg_warns_and_skips(probe, make_twopass, caplog):
    probe["program_version"]["version"] = "7.1"
    probe["streams"][0]["color_transfer"] = "smpte2084"
    with caplog.at_level(logging.WARNING):
        tp = make_twopass()
    assert tp.tonemap is None
    assert "HDR" in caplog.text


# --- a real encode ---


@pytest.mark.slow
@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg is not installed")
def test_real_encode_lands_under_target(tmp_path, monkeypatch):
    # ffmpeg writes its two-pass log files to the working directory
    monkeypatch.chdir(tmp_path)

    # a 2-second test pattern with a tone. Noise keeps it from compressing below the target.
    clip = tmp_path / "clip.mp4"
    video = ffmpeg.input("testsrc=duration=2:size=640x360:rate=30", f="lavfi").filter("noise", alls=60, allf="t")
    audio = ffmpeg.input("sine=duration=2", f="lavfi")
    ffmpeg.output(video, audio, str(clip), **{"b:v": "4M"}).run(quiet=True)

    result = twopass_loop(TwoPass(clip), EncodeSettings(target_filesize=0.5, output=tmp_path / "small.mp4"))

    assert Path(result.output_filename).exists()
    assert result.output_filesize < 0.5
