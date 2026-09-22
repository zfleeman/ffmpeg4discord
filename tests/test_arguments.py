import json
import logging
import socket
import sys

import pytest

from ffmpeg4discord import arguments
from ffmpeg4discord.arguments import (
    _assign_port,
    _extract_times,
    _merge_config_args,
    _normalize_amix_args,
    _parse_astreams,
    _search_for_default_config,
    build_parser,
    get_args,
    is_port_in_use,
    load_config,
    update_args_from_config,
)


@pytest.fixture
def parser():
    return build_parser()


@pytest.fixture
def default_args(parser):
    """The args dict argparse produces for `ff4d file.mp4`, before any config file or post-processing."""
    return vars(parser.parse_args(["file.mp4"]))


@pytest.fixture
def write_config(tmp_path):
    """Write a dict to a JSON file in a temporary folder and return its path."""

    def _write(data, name="config.json"):
        path = tmp_path / name
        path.write_text(json.dumps(data))
        return path

    return _write


# --- the argument parser ---


def test_parser_requires_filename(parser):
    with pytest.raises(SystemExit):
        parser.parse_args([])


def test_parser_defaults(default_args):
    assert default_args["filename"] == "file.mp4"
    assert default_args["output"] == ""
    assert default_args["target_filesize"] == 20
    assert default_args["audio_br"] == 96
    assert default_args["codec"] == "x264"
    assert default_args["crop"] == ""
    assert default_args["resolution"] == ""
    for flag in ("filename_times", "approx", "verbose", "web"):
        assert default_args[flag] is False
    for option in ("framerate", "config", "port", "astreams"):
        assert default_args[option] is None


def test_parser_optional_arguments(parser):
    args = parser.parse_args(
        [
            "file.mp4",
            *("-o", "outdir", "--filename-times", "--approx"),
            *("--from", "00:01:00", "--to", "00:02:00"),
            *("-s", "20", "-a", "128", "-c", "vp9", "-v"),
            *("-x", "10x10x100x100", "-r", "1280x720", "-f", "30"),
            *("--config", "config.json", "--web", "-p", "5050", "--astreams", "0,2"),
        ]
    )
    expected = {
        "output": "outdir",
        "filename_times": True,
        "approx": True,
        "from": "00:01:00",
        "to": "00:02:00",
        "target_filesize": 20,
        "audio_br": 128,
        "codec": "vp9",
        "verbose": True,
        "crop": "10x10x100x100",
        "resolution": "1280x720",
        "framerate": 30,
        "config": "config.json",
        "web": True,
        "port": 5050,
        "astreams": "0,2",
    }
    # every expected key/value pair appears in the parsed args
    assert expected.items() <= vars(args).items()


def test_parser_no_flags_turn_options_off(parser):
    args = parser.parse_args(["file.mp4", "--no-filename-times", "--no-approx", "--no-web", "--no-verbose"])
    assert not args.filename_times
    assert not args.approx
    assert not args.web
    assert not args.verbose


@pytest.mark.parametrize("codec", ["x264", "vp9"])
def test_parser_accepts_codec(parser, codec):
    assert parser.parse_args(["file.mp4", "-c", codec]).codec == codec


def test_parser_rejects_unknown_codec(parser):
    with pytest.raises(SystemExit):
        parser.parse_args(["file.mp4", "-c", "invalid_codec"])


# --- web UI port ---


def test_is_port_in_use_false_for_unused_port():
    # Binding to port 0 makes the OS pick a free port, which is free again once the socket closes.
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("localhost", 0))
        unused_port = s.getsockname()[1]
    assert not is_port_in_use(unused_port)


def test_is_port_in_use_true_for_used_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("localhost", 0))
        s.listen(1)
        assert is_port_in_use(s.getsockname()[1])


def test_assign_port_removes_port_when_web_is_off():
    assert "port" not in _assign_port({"web": False, "port": 5555})


def test_assign_port_picks_a_new_port_when_taken(monkeypatch):
    # the requested port is taken, and the next random pick is free
    monkeypatch.setattr(arguments, "is_port_in_use", lambda port: port == 5555)
    port = _assign_port({"web": True, "port": 5555})["port"]
    assert port != 5555
    assert 5000 <= port <= 6000


# --- config files ---


def test_load_config_valid_json(write_config):
    data = {"key1": "value1", "key2": 2}
    assert load_config(write_config(data)) == data


def test_load_config_invalid_json_raises(tmp_path):
    path = tmp_path / "config.json"
    path.write_text("{invalid json}")
    with pytest.raises(json.JSONDecodeError):
        load_config(path)


def test_load_config_missing_file_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_config(tmp_path / "missing.json")


def test_update_args_from_config_overwrites_defaults(parser, default_args):
    config = {
        "output": "mydir",
        "audio_br": 128,
        "codec": "vp9-speed",
        "filename_times": True,
        "from": "00:00:10",
        "framerate": 60,
        "port": 5050,
    }
    update_args_from_config(default_args, config, parser)
    assert config.items() <= default_args.items()


def test_update_args_from_config_keeps_values_set_on_the_command_line(parser):
    args = vars(parser.parse_args(["file.mp4", "-a", "64"]))
    update_args_from_config(args, {"audio_br": 128}, parser)
    assert args["audio_br"] == 64


def test_update_args_from_config_adds_missing_keys(parser):
    args = {"output": "", "filename": "file.mp4"}
    update_args_from_config(args, {"output": "mydir", "target_filesize": 20}, parser)
    assert args == {"output": "mydir", "filename": "file.mp4", "target_filesize": 20}


def test_merge_config_args_merges_and_removes_config(parser, default_args, write_config):
    default_args["config"] = str(write_config({"output": "from_config", "filename_times": True}))
    result = _merge_config_args(default_args, parser)
    assert result["output"] == "from_config"
    assert result["filename_times"] is True
    assert "config" not in result


def test_merge_config_args_without_config(parser, default_args):
    result = _merge_config_args(default_args, parser)
    assert "config" not in result
    assert result["output"] == ""


def test_merge_config_args_missing_file_raises(parser, default_args, tmp_path):
    default_args["config"] = str(tmp_path / "missing.json")
    with pytest.raises(FileNotFoundError):
        _merge_config_args(default_args, parser)


@pytest.mark.parametrize("platform", ["linux", "win32"])
def test_search_for_default_config_found(monkeypatch, tmp_path, platform):
    (tmp_path / "ffmpeg4discord.json").write_text("{}")
    monkeypatch.setattr(arguments.sys, "platform", platform)
    monkeypatch.setattr(arguments.platformdirs, "user_config_path", lambda *args: tmp_path)
    result = _search_for_default_config({"config": None, "no_config": False})
    assert result["config"] == tmp_path / "ffmpeg4discord.json"


def test_search_for_default_config_none_found(monkeypatch, tmp_path, caplog):
    monkeypatch.setattr(arguments.sys, "platform", "darwin")
    monkeypatch.setattr(arguments.platformdirs, "user_config_path", lambda *args: tmp_path)
    with caplog.at_level(logging.INFO):
        result = _search_for_default_config({"config": None, "no_config": False})
    assert result["config"] is None
    assert "no default configuration files found" in caplog.text.lower()


@pytest.mark.parametrize(
    "args",
    [{"config": "custom.json", "no_config": False}, {"config": None, "no_config": True}],
    ids=["explicit-config", "no-config-flag"],
)
def test_search_for_default_config_skipped(args):
    assert _search_for_default_config(args) is args


# --- post-processing ---


@pytest.mark.parametrize(
    "args, times",
    [
        ({"from": "00:00:10", "to": "00:00:20"}, {"from": "00:00:10", "to": "00:00:20"}),
        ({"from": "00:00:10"}, {"from": "00:00:10"}),
        ({"to": "00:00:20"}, {"to": "00:00:20"}),
        ({}, {}),
    ],
)
def test_extract_times(args, times):
    assert _extract_times(args) == {"times": times}


@pytest.mark.parametrize(
    "raw, parsed",
    [
        ("0, 2,2", [0, 2]),
        ("", None),
        (["0", 2, "2"], [0, 2]),  # a config file can give a list; duplicates are still removed
    ],
)
def test_parse_astreams(raw, parsed):
    assert _parse_astreams({"astreams": raw})["astreams"] == parsed


@pytest.mark.parametrize(
    "raw, message",
    [("0, no", "invalid --astreams format"), (["nope"], "invalid astreams list")],
)
def test_parse_astreams_invalid_logs_error(caplog, raw, message):
    assert _parse_astreams({"astreams": raw})["astreams"] is None
    assert message in caplog.text.lower()


def test_parse_astreams_ignores_negative_index(caplog):
    assert _parse_astreams({"astreams": "0,-1,2"})["astreams"] == [0, 2]
    assert "ignoring negative audio stream index" in caplog.text.lower()


def test_amix_normalize_implies_amix():
    assert _normalize_amix_args({"amix": False, "amix_normalize": True})["amix"] is True


# --- get_args end to end ---


def test_get_args_basic(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["ff4d", "file.mp4", "-o", "outdir", "--target-filesize", "20", "--no-config"])
    args = get_args()
    assert args["filename"] == "file.mp4"
    assert args["output"] == "outdir"
    assert args["target_filesize"] == 20


def test_get_args_parses_astreams_and_amix_normalize(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["ff4d", "file.mp4", "--amix-normalize", "--astreams", "0,1", "--no-config"])
    args = get_args()
    assert args["astreams"] == [0, 1]
    assert args["amix_normalize"] is True
    assert args["amix"] is True
