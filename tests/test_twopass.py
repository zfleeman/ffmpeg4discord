# pylint: disable=W0201, W0212, C0114, C0115, C0116
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
        defaults = {"filename": Path("test.mp4"), "target_filesize": 10, "output": "output.mp4", "codec": "libx264"}
        defaults.update(kwargs)
        return TwoPass(**defaults)

    def patch_ffmpeg_input_output(self, mock_input: MagicMock, mock_output: MagicMock) -> None:
        class FakeStream:
            def __init__(self) -> None:
                self.video = self
                self.audio = self

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

    def test_generate_params(self) -> None:
        tp = self.make_twopass()
        tp.bitrate_dict = {"b:v": 1000000}
        params = tp._generate_params(codec="libx264")
        self.assertEqual(params["pass1"]["c:v"], "libx264")
        self.assertEqual(params["pass2"]["c:v"], "libx264")
        self.assertEqual(params["pass2"]["c:a"], "aac")
        self.assertEqual(params["pass2"]["b:v"], 1000000)

    def test_generate_params_vp9(self) -> None:
        tp = self.make_twopass(
            output="output.webm", codec="libvpx-vp9", vp9_opts={"row-mt": 1, "cpu-used": 4, "deadline": "realtime"}
        )
        tp.bitrate_dict = {"b:v": 500000}
        params = tp._generate_params(codec="libvpx-vp9")
        self.assertEqual(params["pass2"]["c:a"], "libopus")
        self.assertEqual(params["pass2"]["row-mt"], 1)
        self.assertEqual(params["pass2"]["cpu-used"], 4)
        self.assertEqual(params["pass2"]["deadline"], "realtime")
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
        tp = self.make_twopass(output="output.mp4", codec="libvpx-vp9")
        tp.length = 100
        tp.audio_br = 128000
        tp._create_bitrate_dict()
        with self.assertLogs(level="WARNING") as cm:
            tp.run()
        self.assertTrue(any("output file name ends with" in msg.lower() for msg in cm.output))

    @patch("ffmpeg4discord.twopass.os.path.getsize")
    @patch("ffmpeg4discord.twopass.ffmpeg.output")
    @patch("ffmpeg4discord.twopass.ffmpeg.input")
    def test_output_extension_mp4(self, mock_input: MagicMock, mock_output: MagicMock, mock_getsize: MagicMock) -> None:
        self.patch_ffmpeg_input_output(mock_input, mock_output)
        mock_getsize.return_value = 10485760  # 10 MB
        tp = self.make_twopass(output="output.txt", codec="libx264")
        tp.length = 100
        tp.audio_br = 128000
        tp._create_bitrate_dict()
        tp.run()
        self.assertTrue(tp.output.suffix == ".mp4")
        self.assertTrue(tp.output_filename.endswith(".mp4"))

    def test_audio_br_is_multiplied(self) -> None:
        tp = self.make_twopass(audio_br=128)
        self.assertEqual(tp.audio_br, 128000)

    def test_generate_params_with_lower_framerate(self) -> None:
        tp = self.make_twopass(framerate=15)
        tp.bitrate_dict = {"b:v": 1000000}
        # The default init_framerate from fake_probe_result is 30
        params = tp._generate_params(codec="libx264")
        self.assertEqual(params["pass1"]["r"], 15)
        self.assertEqual(params["pass2"]["r"], 15)

    def test_generate_params_with_higher_framerate(self) -> None:
        tp = self.make_twopass(framerate=60)
        tp.bitrate_dict = {"b:v": 1000000}
        with self.assertLogs(level="WARNING") as cm:
            params = tp._generate_params(codec="libx264")
        self.assertNotIn("r", params["pass1"])
        self.assertNotIn("r", params["pass2"])
        self.assertTrue(any("desired framerate" in msg.lower() for msg in cm.output))

    @patch("ffmpeg4discord.twopass.os.path.getsize")
    @patch("ffmpeg4discord.twopass.ffmpeg.output")
    @patch("ffmpeg4discord.twopass.ffmpeg.input")
    def test_output_is_dir(self, mock_input: MagicMock, mock_output: MagicMock, mock_getsize: MagicMock) -> None:
        # Simulate output as a directory
        self.patch_ffmpeg_input_output(mock_input, mock_output)
        mock_getsize.return_value = 10485760  # 10 MB
        # Use a Path object that is a directory
        output_dir = Path("/tmp")
        tp = self.make_twopass(output=str(output_dir))
        # Patch is_dir to return True
        tp.output = output_dir
        tp.length = 100
        tp.audio_br = 128000
        tp._create_bitrate_dict()
        tp.run()
        self.assertTrue(tp.output_filename.startswith(str(output_dir)))
        self.assertIn("small_", tp.output_filename)


if __name__ == "__main__":
    unittest.main()
