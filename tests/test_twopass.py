# pylint: disable=W0201, W0212, C0114, C0115, C0116
import tempfile
import unittest
from pathlib import Path
from typing import Any, Dict
from unittest.mock import MagicMock, patch

from ffmpeg4discord.twopass import TwoPass, seconds_from_ts_string, seconds_to_timestamp


class TestTwoPassUtils(unittest.TestCase):
    def test_seconds_from_ts_string(self) -> None:
        self.assertEqual(seconds_from_ts_string("01:02:03"), 3723)
        self.assertEqual(seconds_from_ts_string("00:00:00"), 0)
        self.assertEqual(seconds_from_ts_string("10:00:00"), 36000)

    def test_seconds_to_timestamp(self) -> None:
        self.assertEqual(seconds_to_timestamp(3723), "01:02:03")
        self.assertEqual(seconds_to_timestamp(0), "00:00:00")
        self.assertEqual(seconds_to_timestamp(36000), "10:00:00")


class TestTwoPass(unittest.TestCase):
    def setUp(self) -> None:
        self.fake_probe_result: Dict[str, Any] = {
            "format": {"duration": "120.0", "size": "53000000"},
            "streams": [
                {
                    "codec_type": "video",
                    "width": 1920,
                    "height": 1080,
                    "r_frame_rate": "30/1",
                    "index": 0,
                },
                {
                    "codec_type": "audio",
                    "bit_rate": "128000",
                    "index": 1,
                },
            ],
        }
        # Patch ffmpeg.probe for all tests
        patcher = patch("ffmpeg4discord.twopass.ffmpeg.probe")
        self.addCleanup(patcher.stop)
        self.mock_probe = patcher.start()
        self.mock_probe.return_value = self.fake_probe_result

    def make_twopass(self, **kwargs: Any) -> TwoPass:
        defaults = {
            "filename": Path("test.mp4"),
            "target_filesize": 10,
            "output": "output.mp4",
            "codec": "x264",
            "amix": False,
            "amix_normalize": False,
            "astreams": None,
        }
        defaults.update(kwargs)
        return TwoPass(**defaults)

    def patch_ffmpeg_input_output(self, mock_input: MagicMock, mock_output: MagicMock) -> None:
        class FakeStream:
            def __init__(self) -> None:
                self.video = self
                self.audio = self

            def __getitem__(self, _key: str) -> "FakeStream":
                return self

            def crop(self, **kwargs: Any) -> "FakeStream":
                _ = kwargs
                return self

            def filter(self, *args: Any, **kwargs: Any) -> "FakeStream":
                _ = args
                _ = kwargs
                return self

        class FakeOutput:
            def global_args(self, *args: Any, **kwargs: Any) -> "FakeOutput":
                _ = args
                _ = kwargs
                return self

            def run(self, **kwargs: Any) -> tuple[bytes, bytes]:
                _ = kwargs
                return (b"", b"")

        mock_input.return_value = FakeStream()
        mock_output.return_value = FakeOutput()

    def test_init_and_probe(self) -> None:
        tp = self.make_twopass()
        self.assertEqual(tp.duration, 120)
        self.assertAlmostEqual(tp.ratio, 1920 / 1080)
        self.assertEqual(tp.init_framerate, 30)
        self.assertEqual(tp.audio_br, 128000)

    def test_process_times_from_dict(self) -> None:
        tp = self.make_twopass(times={"from": "00:00:10", "to": "00:01:00"})
        self.assertEqual(tp.times["ss"], "00:00:10")
        self.assertEqual(tp.times["to"], "00:01:00")
        self.assertEqual(tp.from_seconds, 10)
        self.assertEqual(tp.to_seconds, 60)
        self.assertEqual(tp.length, 50)

    def test_process_times_no_from(self) -> None:
        tp = self.make_twopass(times={"to": "00:01:00"})
        self.assertEqual(tp.times["ss"], "00:00:00")
        self.assertEqual(tp.times["to"], "00:01:00")
        self.assertEqual(tp.from_seconds, 0)
        self.assertEqual(tp.to_seconds, 60)
        self.assertEqual(tp.length, 60)

    def test_process_times_no_to(self) -> None:
        tp = self.make_twopass(times={})
        self.assertEqual(tp.times["ss"], "00:00:00")
        self.assertEqual(tp.times["to"], "00:02:00")
        self.assertEqual(tp.length, 120)

    def test_process_times_from_only(self) -> None:
        tp = self.make_twopass(times={"from": "00:00:10"})
        self.assertEqual(tp.times["ss"], "00:00:10")
        self.assertEqual(tp.times["to"], "00:02:00")
        self.assertEqual(tp.from_seconds, 10)
        self.assertEqual(tp.length, 110)

    def test_time_from_file_name(self) -> None:
        tp = self.make_twopass(filename=Path("000010-000030.mp4"), filename_times=True)
        self.assertEqual(tp.times["ss"], "00:00:10")
        self.assertEqual(tp.times["to"], "00:00:30")
        self.assertEqual(tp.from_seconds, 10)
        self.assertEqual(tp.to_seconds, 30)
        self.assertEqual(tp.length, 20)

    def test_time_from_file_name_only_start(self) -> None:
        tp = self.make_twopass(filename=Path("000010.mp4"), filename_times=True)
        self.assertEqual(tp.times["ss"], "00:00:10")
        self.assertEqual(tp.times["to"], "00:02:00")
        self.assertEqual(tp.from_seconds, 10)
        self.assertEqual(tp.to_seconds, 120)
        self.assertEqual(tp.length, 110)

    @patch("ffmpeg4discord.twopass.os.path.getsize")
    @patch("ffmpeg4discord.twopass.ffmpeg.output")
    @patch("ffmpeg4discord.twopass.ffmpeg.input")
    def test_run(self, mock_input: MagicMock, mock_output: MagicMock, mock_getsize: MagicMock) -> None:
        self.patch_ffmpeg_input_output(mock_input, mock_output)
        mock_getsize.return_value = 10485760  # 10 MB
        tp = self.make_twopass(verbose=True)
        size = tp.run()
        self.assertAlmostEqual(size, 10, places=2)

    @patch("ffmpeg4discord.twopass.os.path.getsize")
    @patch("ffmpeg4discord.twopass.ffmpeg.output")
    @patch("ffmpeg4discord.twopass.ffmpeg.input")
    def test_run_two_pass_calls_and_audio_included(
        self, mock_input: MagicMock, mock_output: MagicMock, mock_getsize: MagicMock
    ) -> None:
        """Covers the `output_streams = [video, audio] if audio else [video]` branch where audio is present,
        and asserts first/second pass `run()` kwargs are correct.
        """

        # Fake ffmpeg input stream
        class FakeStream:
            def __init__(self) -> None:
                self.video = self
                self.audio = self

            def __getitem__(self, _key: str) -> "FakeStream":
                return self

            def crop(self, **kwargs: Any) -> "FakeStream":
                _ = kwargs
                return self

            def filter(self, *args: Any, **kwargs: Any) -> "FakeStream":
                _ = args
                _ = kwargs
                return self

        mock_input.return_value = FakeStream()
        mock_getsize.return_value = 10485760  # 10 MB

        # Make ffmpeg.output return two different objects (pass1 vs pass2)
        pass1 = MagicMock()
        pass1.global_args.return_value = pass1
        pass1.run.return_value = (b"", b"")

        pass2 = MagicMock()
        pass2.global_args.return_value = pass2
        pass2.run.return_value = (b"", b"")

        mock_output.side_effect = [pass1, pass2]

        tp = self.make_twopass(verbose=False, amix=False, astreams=None)
        tp.length = 100
        tp.run()

        # First pass: output(video, "pipe:", ...)
        first_args, _first_kwargs = mock_output.call_args_list[0]
        self.assertEqual(first_args[1], "pipe:")
        pass1.run.assert_called_once()
        _, pass1_run_kwargs = pass1.run.call_args
        self.assertTrue(pass1_run_kwargs.get("capture_stdout"))

        # Second pass: output(video, audio, output_filename, ...)
        second_args, _second_kwargs = mock_output.call_args_list[1]
        self.assertEqual(second_args[-1], tp.output_filename)
        self.assertEqual(len(second_args), 3)

        pass2.run.assert_called_once()
        _, pass2_run_kwargs = pass2.run.call_args
        self.assertTrue(pass2_run_kwargs.get("overwrite_output"))

    @patch("ffmpeg4discord.twopass.os.path.getsize")
    @patch("ffmpeg4discord.twopass.ffmpeg.output")
    @patch("ffmpeg4discord.twopass.ffmpeg.input")
    def test_run_no_audio_stream_outputs_video_only(
        self, mock_input: MagicMock, mock_output: MagicMock, mock_getsize: MagicMock
    ) -> None:
        # Remove audio streams from probe
        self.fake_probe_result["streams"] = [self.fake_probe_result["streams"][0]]
        self.mock_probe.return_value = self.fake_probe_result

        self.patch_ffmpeg_input_output(mock_input, mock_output)
        mock_getsize.return_value = 10485760  # 10 MB

        # Provide an audio bitrate explicitly so bitrate calc doesn't crash.
        tp = self.make_twopass(audio_br=96)
        tp.length = 100
        tp.run()

        # First pass call: output(video, "pipe:", ...)
        # Second pass call: output(video, output_filename, ...)
        self.assertGreaterEqual(len(mock_output.call_args_list), 2)
        second_pass_args, _second_pass_kwargs = mock_output.call_args_list[-1]
        # second pass positional args should be: (video_stream, output_filename)
        self.assertEqual(len(second_pass_args), 2)
        self.assertEqual(second_pass_args[1], tp.output_filename)

    @patch("ffmpeg4discord.twopass.os.path.getsize")
    @patch("ffmpeg4discord.twopass.ffmpeg.output")
    @patch("ffmpeg4discord.twopass.ffmpeg.input")
    def test_run_no_audio_flag_omits_audio_even_if_present(
        self, mock_input: MagicMock, mock_output: MagicMock, mock_getsize: MagicMock
    ) -> None:
        """Covers twopass.py lines 282-283: `output_streams = [video, audio] if audio and not self.no_audio else [video]`.

        Ensures that when an audio stream exists but `no_audio=True`, the second pass outputs *video only*.
        """

        # Fake ffmpeg input stream with both video and audio present.
        class FakeStream:
            def __init__(self) -> None:
                self.video = self
                self.audio = self

            def __getitem__(self, _key: str) -> "FakeStream":
                return self

            def crop(self, **kwargs: Any) -> "FakeStream":
                _ = kwargs
                return self

            def filter(self, *args: Any, **kwargs: Any) -> "FakeStream":
                _ = args
                _ = kwargs
                return self

        mock_input.return_value = FakeStream()
        mock_getsize.return_value = 10485760  # 10 MiB-ish

        # Make ffmpeg.output return two different objects (pass1 vs pass2)
        pass1 = MagicMock()
        pass1.global_args.return_value = pass1
        pass1.run.return_value = (b"", b"")

        pass2 = MagicMock()
        pass2.global_args.return_value = pass2
        pass2.run.return_value = (b"", b"")

        mock_output.side_effect = [pass1, pass2]

        tp = self.make_twopass(no_audio=True, amix=False)
        tp.length = 100
        tp.run()

        # Second pass should not include audio even though it's available.
        second_pass_args, _second_pass_kwargs = mock_output.call_args_list[1]
        self.assertEqual(len(second_pass_args), 2)
        self.assertEqual(second_pass_args[1], tp.output_filename)

    def test_generate_params(self) -> None:
        tp = self.make_twopass()
        tp.bitrate_dict = {"b:v": 1000000}
        params = tp._generate_params(codec="x264")
        self.assertEqual(params["pass1"]["c:v"], "libx264")
        self.assertEqual(params["pass2"]["c:v"], "libx264")
        self.assertEqual(params["pass2"]["c:a"], "aac")
        self.assertEqual(params["pass2"]["b:v"], 1000000)

    def test_generate_params_applies_overrides_both_to_both_passes(self) -> None:
        """Covers twopass.py lines 282-283 (apply `overrides['both']` to both passes).

        The built-in `CODEC_OVERRIDES` currently doesn’t define a `both` section, so we patch it
        for this test and confirm the shared param is applied to both pass dicts.
        """

        tp = self.make_twopass()
        tp.bitrate_dict = {"b:v": 1000000}

        with patch.dict(
            "ffmpeg4discord.twopass.CODEC_OVERRIDES",
            {"x264": {"both": {"pix_fmt": "yuv420p"}}},
            clear=False,
        ):
            params = tp._generate_params(codec="x264")

        self.assertEqual(params["pass1"]["pix_fmt"], "yuv420p")
        self.assertEqual(params["pass2"]["pix_fmt"], "yuv420p")

    def test_generate_params_x265_uses_x265_params_and_removes_pass(self) -> None:
        """Covers twopass.py lines 262-265 (x265 two-pass special casing).

        Ensures `pass` is removed and `x265-params` is used instead.
        """

        tp = self.make_twopass(codec="x265")
        tp.bitrate_dict = {"b:v": 1000000}

        params = tp._generate_params(codec="x265")

        self.assertNotIn("pass", params["pass1"])
        self.assertNotIn("pass", params["pass2"])
        self.assertEqual(params["pass1"]["x265-params"], "pass=1")
        self.assertEqual(params["pass2"]["x265-params"], "pass=2")

        # Sanity checks that other expected params are still present
        self.assertEqual(params["pass2"]["c:v"], "libx265")
        self.assertEqual(params["pass2"]["c:a"], "aac")

    @patch("ffmpeg4discord.twopass.ffmpeg.filter")
    def test_apply_audio_filters_subset_and_mix(self, mock_filter: MagicMock) -> None:
        tp = self.make_twopass(amix=True, astreams=[0])

        class DummyInput:
            audio = "AUDIO_DEFAULT"

            def __getitem__(self, _key: str) -> str:
                return "STREAM"  # we don't care which one for this test

        inp = DummyInput()
        _ = tp._apply_audio_filters(inp)
        mock_filter.assert_called_once()

    @patch("ffmpeg4discord.twopass.ffmpeg.filter")
    def test_apply_audio_filters_mix_all_when_astreams_none(self, mock_filter: MagicMock) -> None:
        """Covers `_apply_audio_filters()` branch:
        `if self.astreams is None: selected_positions = list(range(len(self.audio_streams)))`
        """

        # Add a second audio stream so we can prove we mix multiple tracks.
        self.fake_probe_result["streams"].append({"codec_type": "audio", "bit_rate": "128000", "index": 2})
        self.mock_probe.return_value = self.fake_probe_result

        tp = self.make_twopass(amix=True, astreams=None, amix_normalize=True)

        class DummyInput:
            audio = "AUDIO_DEFAULT"

            def __getitem__(self, key: str) -> str:
                # _apply_audio_filters requests "a:0", "a:1", ...
                return key

        inp = DummyInput()
        _ = tp._apply_audio_filters(inp)

        mock_filter.assert_called_once()
        (to_merge, filter_name), kwargs = mock_filter.call_args
        self.assertEqual(filter_name, "amix")
        self.assertEqual(len(to_merge), 2)
        self.assertEqual(to_merge, ["a:0", "a:1"])
        self.assertEqual(kwargs.get("normalize"), 1)
        self.assertEqual(kwargs.get("inputs"), 2)

    @patch("ffmpeg4discord.twopass.ffmpeg.filter")
    def test_apply_audio_filters_mix_with_empty_selection_returns_none(self, mock_filter: MagicMock) -> None:
        """Covers `if not selected_positions: return None` branch."""

        tp = self.make_twopass(amix=True, astreams=[])

        class DummyInput:
            audio = "AUDIO_DEFAULT"

            def __getitem__(self, key: str) -> str:
                return key

        inp = DummyInput()
        audio = tp._apply_audio_filters(inp)
        self.assertIsNone(audio)
        mock_filter.assert_not_called()

    def test_apply_audio_filters_subset_no_mix_returns_default_audio(self) -> None:
        # In non-mixing mode, selection is ignored and we keep the default/first audio track.
        tp = self.make_twopass(amix=False, astreams=[1])

        class DummyInput:
            audio = "AUDIO_DEFAULT"

            def __getitem__(self, key: str) -> str:
                return f"{key}_OBJ"

        inp = DummyInput()
        audio = tp._apply_audio_filters(inp)
        self.assertEqual(audio, "AUDIO_DEFAULT")

    def test_apply_audio_filters_none_selection_returns_default_audio(self) -> None:
        tp = self.make_twopass(amix=False, astreams=None)

        class DummyInput:
            audio = "AUDIO_DEFAULT"

            def __getitem__(self, key: str) -> str:
                return f"{key}_OBJ"

        inp = DummyInput()
        audio = tp._apply_audio_filters(inp)
        self.assertEqual(audio, "AUDIO_DEFAULT")

    def test_generate_params_vp9(self) -> None:
        tp = self.make_twopass(
            output="output.webm",
            codec="vp9",
        )
        tp.bitrate_dict = {"b:v": 500000}
        params = tp._generate_params(codec="vp9")
        self.assertEqual(params["pass2"]["c:a"], "libopus")
        self.assertEqual(params["pass2"]["row-mt"], 1)
        self.assertEqual(params["pass2"]["cpu-used"], 5)
        self.assertEqual(params["pass2"]["deadline"], "good")
        self.assertEqual(params["pass2"]["b:v"], 500000)

    def test_apply_video_filters_crop_and_resolution(self) -> None:
        tp = self.make_twopass(crop="10x20x640x360", resolution="1280x720")

        class DummyVideo:
            def crop(self, **kwargs: Any) -> "DummyVideo":
                _ = kwargs
                self.cropped = True
                return self

            def filter(self, *args: Any, **kwargs: Any) -> "DummyVideo":
                _ = args
                _ = kwargs
                self.filtered = True
                return self

        video = DummyVideo()
        result = tp._apply_video_filters(video)
        self.assertTrue(hasattr(result, "cropped"))
        self.assertTrue(hasattr(result, "filtered"))

    def test_time_paradox_raises(self) -> None:
        with self.assertRaises(ValueError):
            self.make_twopass(times={"from": "00:02:00", "to": "00:01:00"})

    def test_target_fs_greater_than_input_raises(self) -> None:
        with self.assertRaises(ValueError):
            self.make_twopass(target_filesize=51)

    def test_time_from_file_name_invalid(self) -> None:
        with self.assertLogs(level="WARNING") as cm:
            tp = self.make_twopass(filename=Path("badname.mp4"), filename_times=True)
        self.assertTrue(any("invalid time format" in msg.lower() for msg in cm.output))
        self.assertEqual(tp.length, 120)
        self.assertEqual(tp.times["ss"], "00:00:00")
        self.assertEqual(tp.times["to"], "00:02:00")

    def test_create_bitrate_dict(self) -> None:
        tp = self.make_twopass()
        tp.length = 100
        tp.audio_br = 128000
        tp._create_bitrate_dict()
        self.assertIn("b:v", tp.bitrate_dict)
        self.assertIn("minrate", tp.bitrate_dict)
        self.assertIn("maxrate", tp.bitrate_dict)
        self.assertIn("bufsize", tp.bitrate_dict)

    def test_create_bitrate_dict_raises_on_zero_length(self) -> None:
        tp = self.make_twopass()
        tp.length = 0
        tp.audio_br = 128000
        with self.assertRaises(ValueError):
            tp._create_bitrate_dict()

    def test_warning_no_audio_stream(self) -> None:
        # Remove audio stream
        self.fake_probe_result["streams"] = [self.fake_probe_result["streams"][0]]
        with self.assertLogs(level="WARNING") as cm:
            _ = self.make_twopass()
        self.assertTrue(any("no audio stream found" in msg.lower() for msg in cm.output))
        # Restore audio stream
        self.fake_probe_result["streams"].append({"codec_type": "audio", "bit_rate": "128000", "index": 1})

    def test_warning_aspect_ratio_mismatch(self) -> None:
        tp = self.make_twopass(crop="10x20x640x360", resolution="1280x720")

        class DummyVideo:
            def crop(self, **kwargs: Any) -> "DummyVideo":
                _ = kwargs
                return self

            def filter(self, *args: Any, **kwargs: Any) -> "DummyVideo":
                _ = args
                _ = kwargs
                return self

        video = DummyVideo()
        tp.ratio = 640 / 360  # 16:9
        # 1280x720 is also 16:9, so to force a mismatch, use 1280x800
        tp.resolution = "1280x800"
        with self.assertLogs(level="WARNING") as cm:
            tp._apply_video_filters(video)
        self.assertTrue(any("aspect ratio does not match" in msg.lower() for msg in cm.output))

    @patch("ffmpeg4discord.twopass.os.path.getsize")
    @patch("ffmpeg4discord.twopass.ffmpeg.output")
    @patch("ffmpeg4discord.twopass.ffmpeg.input")
    def test_warning_output_extension_mismatch(
        self, mock_input: MagicMock, mock_output: MagicMock, mock_getsize: MagicMock
    ) -> None:
        # Output is .mp4 but codec is vp9 (should be .webm)
        self.patch_ffmpeg_input_output(mock_input, mock_output)
        mock_getsize.return_value = 10485760  # 10 MB
        tp = self.make_twopass(output="output.mp4", codec="vp9-speed")
        tp.length = 100
        tp.audio_br = 128000
        tp._create_bitrate_dict()
        with self.assertLogs(level="WARNING") as cm:
            tp.run()

        self.assertTrue(any("output file name ends with" in msg.lower() for msg in cm.output))
        # Ensure suffix was corrected to match codec
        self.assertEqual(tp.output.suffix, ".webm")
        self.assertTrue(tp.output_filename.endswith(".webm"))

    @patch("ffmpeg4discord.twopass.os.path.getsize")
    @patch("ffmpeg4discord.twopass.ffmpeg.output")
    @patch("ffmpeg4discord.twopass.ffmpeg.input")
    def test_output_extension_mp4(self, mock_input: MagicMock, mock_output: MagicMock, mock_getsize: MagicMock) -> None:
        self.patch_ffmpeg_input_output(mock_input, mock_output)
        mock_getsize.return_value = 10485760  # 10 MB
        tp = self.make_twopass(output="output.txt", codec="x264")
        tp.length = 100
        tp.audio_br = 128000
        tp._create_bitrate_dict()
        tp.run()
        self.assertTrue(tp.output.suffix == ".mp4")
        self.assertTrue(tp.output_filename.endswith(".mp4"))

    @patch("ffmpeg4discord.twopass.os.path.getsize")
    @patch("ffmpeg4discord.twopass.ffmpeg.output")
    @patch("ffmpeg4discord.twopass.ffmpeg.input")
    def test_warning_output_extension_mismatch_x264(
        self, mock_input: MagicMock, mock_output: MagicMock, mock_getsize: MagicMock
    ) -> None:
        # Output is .webm but codec is x264 (should be .mp4)
        self.patch_ffmpeg_input_output(mock_input, mock_output)
        mock_getsize.return_value = 10485760  # 10 MB
        tp = self.make_twopass(output="output.webm", codec="x264")
        tp.length = 100
        tp.audio_br = 128000
        tp._create_bitrate_dict()
        with self.assertLogs(level="WARNING") as cm:
            tp.run()

        self.assertTrue(any("output file name ends with" in msg.lower() for msg in cm.output))
        self.assertEqual(tp.output.suffix, ".mp4")
        self.assertTrue(tp.output_filename.endswith(".mp4"))

    def test_audio_br_is_multiplied(self) -> None:
        tp = self.make_twopass(audio_br=128)
        self.assertEqual(tp.audio_br, 128000)

    def test_generate_params_with_lower_framerate(self) -> None:
        tp = self.make_twopass(framerate=15)
        tp.bitrate_dict = {"b:v": 1000000}
        # The default init_framerate from fake_probe_result is 30
        params = tp._generate_params(codec="x264")
        self.assertEqual(params["pass1"]["r"], 15)
        self.assertEqual(params["pass2"]["r"], 15)

    def test_generate_params_with_higher_framerate(self) -> None:
        tp = self.make_twopass(framerate=60)
        tp.bitrate_dict = {"b:v": 1000000}
        with self.assertLogs(level="WARNING") as cm:
            params = tp._generate_params(codec="x264")
        self.assertNotIn("r", params["pass1"])
        self.assertNotIn("r", params["pass2"])
        self.assertTrue(any("desired framerate" in msg.lower() for msg in cm.output))

    @patch("ffmpeg4discord.twopass.os.path.getsize")
    @patch("ffmpeg4discord.twopass.ffmpeg.output")
    @patch("ffmpeg4discord.twopass.ffmpeg.input")
    def test_output_is_dir(self, mock_input: MagicMock, mock_output: MagicMock, mock_getsize: MagicMock) -> None:
        # Simulate output as a directory in a cross-platform way
        self.patch_ffmpeg_input_output(mock_input, mock_output)
        mock_getsize.return_value = 10485760  # 10 MB

        with tempfile.TemporaryDirectory() as tmpdir:
            # Pass the temporary directory as the output target
            tp = self.make_twopass(output=tmpdir)
            tp.length = 100
            tp.audio_br = 128000
            tp._create_bitrate_dict()
            tp.run()
            self.assertTrue(tp.output_filename.startswith(tmpdir))
            self.assertIn("small_", tp.output_filename)


if __name__ == "__main__":
    unittest.main()
