# pylint: disable=W0212, C0114, C0115, C0116
import json
import socket
import sys
import tempfile
import unittest
from argparse import ArgumentParser
from pathlib import Path
from unittest.mock import patch

from ffmpeg4discord.arguments import (
    _assign_port,
    _extract_times,
    _normalize_amix_args,
    _parse_astreams,
    _search_for_default_config,
    build_parser,
    get_args,
    is_port_in_use,
    load_config,
    update_args_from_config,
)


class TestArguments(unittest.TestCase):
    def setUp(self) -> None:
        self.parser = build_parser()
        self.default_args = {
            "filename": "file.mp4",
            "output": "",
            "target_filesize": 10,
            "filename_times": False,
            "audio_br": 96,
            "codec": "libx264",
            "approx": False,
            "from": None,
            "to": None,
            "verbose": False,
            "crop": "",
            "resolution": "",
            "framerate": None,
            "config": None,
            "web": False,
            "port": None,
            "astreams": None,
        }
        self.default_config = {
            "output": "mydir",
            "target_filesize": 5,
            "audio_br": 128,
            "codec": "vp9",
            "filename_times": True,
            "approx": True,
            "from": "00:00:10",
            "to": "00:00:20",
            "verbose": True,
            "crop": "10x10x100x100",
            "resolution": "1280x720",
            "framerate": 60,
            "web": True,
            "port": 5050,
            "astreams": "0,2",
        }

    def tearDown(self) -> None:
        pass

    def get_args(self, overrides=None):
        args = self.default_args.copy()
        if overrides:
            args.update(overrides)
        return args

    def get_config(self, overrides=None):
        config = self.default_config.copy()
        if overrides:
            config.update(overrides)
        return config

    def test_build_parser_returns_argumentparser(self):
        self.assertIsInstance(self.parser, ArgumentParser)

    def test_parser_required_filename(self):
        with self.assertRaises(SystemExit):
            self.parser.parse_args([])  # filename is required

    def test_parser_accepts_filename(self):
        args = self.parser.parse_args(["input.mp4"])
        self.assertEqual(args.filename, "input.mp4")

    def test_parser_defaults_and_types(self):
        args = self.parser.parse_args(["file.mp4"])
        self.assertEqual(args.output, "")
        self.assertFalse(args.filename_times)
        self.assertFalse(args.approx)
        self.assertEqual(args.target_filesize, 10)
        self.assertEqual(args.audio_br, 96)
        self.assertEqual(args.codec, "x264")
        self.assertFalse(args.verbose)
        self.assertEqual(args.crop, "")
        self.assertEqual(args.resolution, "")
        self.assertIsNone(args.framerate)
        self.assertIsNone(args.config)
        self.assertFalse(args.web)
        self.assertIsNone(args.port)
        self.assertIsNone(getattr(args, "astreams", None))

    def test_parser_optional_arguments(self):
        args = self.parser.parse_args(
            [
                "file.mp4",
                "-o",
                "outdir",
                "--filename-times",
                "--approx",
                "--from",
                "00:01:00",
                "--to",
                "00:02:00",
                "-s",
                "5",
                "-a",
                "128",
                "-c",
                "vp9",
                "-v",
                "-x",
                "10x10x100x100",
                "-r",
                "1280x720",
                "-f",
                "30",
                "--config",
                "config.json",
                "--web",
                "-p",
                "5050",
                "--astreams",
                "0,2",
            ]
        )
        self.assertEqual(args.output, "outdir")
        self.assertTrue(args.filename_times)
        self.assertTrue(args.approx)
        self.assertEqual(getattr(args, "from"), "00:01:00")
        self.assertEqual(args.to, "00:02:00")
        self.assertEqual(args.target_filesize, 5)
        self.assertEqual(args.audio_br, 128)
        self.assertEqual(args.codec, "vp9")
        self.assertTrue(args.verbose)
        self.assertEqual(args.crop, "10x10x100x100")
        self.assertEqual(args.resolution, "1280x720")
        self.assertEqual(args.framerate, 30)
        self.assertEqual(args.config, "config.json")
        self.assertTrue(args.web)
        self.assertEqual(args.port, 5050)
        self.assertEqual(args.astreams, "0,2")

    def test_parser_boolean_optional_action_false(self):
        args = self.parser.parse_args(["file.mp4", "--no-filename-times", "--no-approx", "--no-web", "--no-verbose"])
        self.assertFalse(args.filename_times)
        self.assertFalse(args.approx)
        self.assertFalse(args.web)
        self.assertFalse(args.verbose)

    def test_parser_codec_choices(self):
        args = self.parser.parse_args(["file.mp4", "-c", "x264"])
        self.assertEqual(args.codec, "x264")
        args = self.parser.parse_args(["file.mp4", "-c", "vp9"])
        self.assertEqual(args.codec, "vp9")
        with self.assertRaises(SystemExit):
            self.parser.parse_args(["file.mp4", "-c", "invalid_codec"])

    def test_is_port_in_use_false_for_unused_port(self):
        # Find an unused port by binding to port 0 (OS assigns a free port)
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("localhost", 0))
            unused_port = s.getsockname()[1]
        # After closing the socket, the port should be free
        self.assertFalse(is_port_in_use(unused_port))

    def test_is_port_in_use_true_for_used_port(self):
        # Bind to a port and keep it open to simulate a port in use
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.bind(("localhost", 0))
        used_port = s.getsockname()[1]
        s.listen(1)
        try:
            self.assertTrue(is_port_in_use(used_port))
        finally:
            s.close()

    def test_load_config_valid_json(self):

        config_data = {"key1": "value1", "key2": 2}
        with tempfile.NamedTemporaryFile("w+", delete=False, suffix=".json") as tmp:
            json.dump(config_data, tmp)
            tmp_path = Path(tmp.name)
        try:
            loaded = load_config(tmp_path)
            self.assertEqual(loaded, config_data)
        finally:
            tmp_path.unlink()

    def test_load_config_invalid_json_raises(self):

        with tempfile.NamedTemporaryFile("w+", delete=False, suffix=".json") as tmp:
            tmp.write("{invalid json}")
            tmp_path = Path(tmp.name)
        try:
            with self.assertRaises(json.JSONDecodeError):
                load_config(tmp_path)
        finally:
            tmp_path.unlink()

    def test_load_config_file_not_found(self):

        non_existent = Path("this_file_should_not_exist_12345.json")
        with self.assertRaises(FileNotFoundError):
            load_config(non_existent)

    def test_update_args_from_config_overwrites_default_and_empty(self):

        parser = build_parser()
        # args with default and empty values
        args = {
            "output": "",
            "target_filesize": 10,
            "audio_br": 96,
            "filename": "file.mp4",
            "codec": "x264",
            "filename_times": False,
            "approx": False,
            "from": None,
            "to": None,
            "verbose": False,
            "crop": "",
            "resolution": "",
            "framerate": None,
            "config": None,
            "web": False,
            "port": None,
            "astreams": None,
        }
        config = {
            "output": "mydir",
            "target_filesize": 5,
            "audio_br": 128,
            "codec": "vp9-speed",
            "filename_times": True,
            "approx": True,
            "from": "00:00:10",
            "to": "00:00:20",
            "verbose": True,
            "crop": "10x10x100x100",
            "resolution": "1280x720",
            "framerate": 60,
            "web": True,
            "port": 5050,
            "astreams": "0,2",
        }
        update_args_from_config(args, config, parser)
        self.assertEqual(args["output"], "mydir")
        self.assertEqual(args["target_filesize"], 5)
        self.assertEqual(args["audio_br"], 128)
        self.assertEqual(args["codec"], "vp9-speed")
        self.assertTrue(args["filename_times"])
        self.assertTrue(args["approx"])
        self.assertEqual(args["from"], "00:00:10")
        self.assertEqual(args["to"], "00:00:20")
        self.assertTrue(args["verbose"])
        self.assertEqual(args["crop"], "10x10x100x100")
        self.assertEqual(args["resolution"], "1280x720")
        self.assertEqual(args["framerate"], 60)
        self.assertTrue(args["web"])
        self.assertEqual(args["port"], 5050)

    def test_update_args_from_config_missing_keys(self):

        parser = build_parser()
        args = {
            "output": "",
            "filename": "file.mp4",
        }
        config = {
            "output": "mydir",
            "target_filesize": 5,
        }
        # Missing keys should be inserted without raising
        update_args_from_config(args, config, parser)
        self.assertEqual(args["output"], "mydir")
        self.assertEqual(args["target_filesize"], 5)

    def test_merge_config_args_merges_and_removes_config(self):
        # Prepare args with config file
        parser = build_parser()
        config_data = {
            "output": "from_config",
            "target_filesize": 7,
            "filename_times": True,
        }
        with tempfile.NamedTemporaryFile("w+", delete=False, suffix=".json") as tmp:
            json.dump(config_data, tmp)
            tmp_path = Path(tmp.name)
        try:
            args = {
                "filename": "file.mp4",
                "output": "",
                "target_filesize": 10,
                "filename_times": False,
                "config": str(tmp_path),
                "audio_br": 96,
                "codec": "libx264",
                "approx": False,
                "from": None,
                "to": None,
                "verbose": False,
                "crop": "",
                "resolution": "",
                "framerate": None,
                "web": False,
                "port": None,
                "astreams": None,
            }
            result = __import__("ffmpeg4discord.arguments").arguments._merge_config_args(args.copy(), parser)
            self.assertEqual(result["output"], "from_config")
            self.assertEqual(result["target_filesize"], 7)
            self.assertTrue(result["filename_times"])
            self.assertNotIn("config", result)
        finally:
            tmp_path.unlink()

    def test_merge_config_args_no_config_key(self):
        parser = build_parser()
        args = {
            "filename": "file.mp4",
            "output": "",
            "target_filesize": 10,
            "filename_times": False,
            "audio_br": 96,
            "codec": "libx264",
            "approx": False,
            "from": None,
            "to": None,
            "verbose": False,
            "crop": "",
            "resolution": "",
            "framerate": None,
            "web": False,
            "port": None,
            "astreams": None,
        }
        result = __import__("ffmpeg4discord.arguments").arguments._merge_config_args(args.copy(), parser)
        self.assertNotIn("config", result)
        self.assertEqual(result["output"], "")

    def test_merge_config_args_config_file_not_found(self):
        parser = build_parser()
        args = {
            "filename": "file.mp4",
            "output": "",
            "target_filesize": 10,
            "filename_times": False,
            "config": "nonexistent_config_file_12345.json",
            "audio_br": 96,
            "codec": "libx264",
            "approx": False,
            "from": None,
            "to": None,
            "verbose": False,
            "crop": "",
            "resolution": "",
            "framerate": None,
            "web": False,
            "port": None,
            "astreams": None,
        }
        with self.assertRaises(FileNotFoundError):
            __import__("ffmpeg4discord.arguments").arguments._merge_config_args(args.copy(), parser)

    def test_assign_port_removes_port_when_web_false(self):
        args = {"web": False, "port": 5555}
        result = _assign_port(args)
        self.assertNotIn("port", result)

    def test_assign_port_assigns_and_checks_port(self):
        # Patch is_port_in_use to simulate port in use once, then free
        import ffmpeg4discord.arguments as arguments_mod  # pylint: disable=C0415

        calls = []

        def fake_is_port_in_use(port):
            calls.append(port)
            return len(calls) == 1  # First call: in use, second: free

        old_is_port_in_use = arguments_mod.is_port_in_use
        arguments_mod.is_port_in_use = fake_is_port_in_use
        try:
            args = {"web": True, "port": 5555}
            result = _assign_port(args)
            self.assertIn("port", result)
            self.assertNotEqual(result["port"], 5555)  # Should not be the first port if in use
            self.assertTrue(5000 <= result["port"] <= 6000)
        finally:
            arguments_mod.is_port_in_use = old_is_port_in_use

    def test_extract_times_both_from_and_to(self):
        args = {"from": "00:00:10", "to": "00:00:20"}
        result = _extract_times(args)
        self.assertEqual(result["times"], {"from": "00:00:10", "to": "00:00:20"})
        self.assertNotIn("from", result)
        self.assertNotIn("to", result)

    def test_extract_times_only_from(self):
        args = {"from": "00:00:10"}
        result = _extract_times(args)
        self.assertEqual(result["times"], {"from": "00:00:10"})
        self.assertNotIn("from", result)
        self.assertNotIn("to", result)

    def test_extract_times_only_to(self):
        args = {"to": "00:00:20"}
        result = _extract_times(args)
        self.assertEqual(result["times"], {"to": "00:00:20"})
        self.assertNotIn("from", result)
        self.assertNotIn("to", result)

    def test_extract_times_neither(self):
        args = {}
        result = _extract_times(args)
        self.assertEqual(result["times"], {})
        self.assertNotIn("from", result)
        self.assertNotIn("to", result)

    def test_parse_astreams_valid(self):
        args = {"astreams": "0, 2,2"}
        result = _parse_astreams(args)
        self.assertEqual(result["astreams"], [0, 2])

    def test_parse_astreams_invalid(self):
        args = {"astreams": "0, no"}
        with self.assertLogs(level="ERROR") as cm:
            result = _parse_astreams(args)
        self.assertIsNone(result["astreams"])
        self.assertTrue(any("invalid --astreams format" in msg.lower() for msg in cm.output))

    def test_parse_astreams_empty_string(self):
        args = {"astreams": ""}
        result = _parse_astreams(args)
        self.assertIsNone(result["astreams"])

    def test_parse_astreams_list_valid(self):
        args = {"astreams": ["0", 2, "2"]}
        result = _parse_astreams(args)
        # Note: list-input mode does not de-dupe; normalize loop does.
        self.assertEqual(result["astreams"], [0, 2])

    def test_parse_astreams_list_invalid(self):
        args = {"astreams": ["nope"]}
        with self.assertLogs(level="ERROR") as cm:
            result = _parse_astreams(args)
        self.assertIsNone(result["astreams"])
        self.assertTrue(any("invalid astreams list" in msg.lower() for msg in cm.output))

    def test_parse_astreams_negative_index_warns_and_is_ignored(self):
        args = {"astreams": "0,-1,2"}
        with self.assertLogs(level="WARNING") as cm:
            result = _parse_astreams(args)
        self.assertEqual(result["astreams"], [0, 2])
        self.assertTrue(any("ignoring negative audio stream index" in msg.lower() for msg in cm.output))

    def test_normalize_amix_args_implies_amix(self):
        args = {"amix": False, "amix_normalize": True}
        result = _normalize_amix_args(args)
        self.assertTrue(result["amix"])

    def test_search_for_default_config_linux_config_found(self):
        args = {"config": None, "no_config": False}
        with (
            patch("ffmpeg4discord.arguments.sys.platform", "linux"),
            patch("ffmpeg4discord.arguments.platformdirs.user_config_path") as mock_user_config_path,
        ):
            mock_user_config_path.return_value = Path("/tmp")
            with patch.object(Path, "exists", return_value=True), patch.object(Path, "is_file", return_value=True):
                result = _search_for_default_config(args)
        self.assertEqual(result["config"], Path("/tmp/ff4d.json"))

    def test_search_for_default_config_no_defaults_found(self):
        args = {"config": None, "no_config": False}
        with (
            patch("ffmpeg4discord.arguments.sys.platform", "darwin"),
            patch("ffmpeg4discord.arguments.platformdirs.user_config_path") as mock_user_config_path,
        ):
            mock_user_config_path.return_value = Path("/tmp")
            with patch.object(Path, "exists", return_value=False), patch.object(Path, "is_file", return_value=False):
                with self.assertLogs(level="INFO") as cm:
                    result = _search_for_default_config(args)
        self.assertIsNone(result.get("config"))
        self.assertTrue(any("no default configuration files found" in msg.lower() for msg in cm.output))

    def test_get_args_parses_astreams_and_amix_normalize(self):
        test_argv = ["prog", "file.mp4", "--amix-normalize", "--astreams", "0,1"]
        with patch.object(sys, "argv", test_argv):
            args = get_args()
        self.assertEqual(args["astreams"], [0, 1])
        self.assertTrue(args["amix_normalize"])
        self.assertTrue(args["amix"])  # implied by normalize

    def test_get_args_basic(self):
        test_argv = ["prog", "file.mp4", "-o", "outdir", "--target-filesize", "5"]
        with patch.object(sys, "argv", test_argv):
            args = get_args()
            self.assertEqual(args["filename"], "file.mp4")
            self.assertEqual(args["output"], "outdir")
            self.assertEqual(args["target_filesize"], 5)


if __name__ == "__main__":
    unittest.main()
