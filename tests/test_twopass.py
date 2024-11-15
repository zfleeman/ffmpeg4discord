import unittest
from unittest.mock import patch, MagicMock
from ffmpeg4discord.twopass import TwoPass
from pathlib import Path


class TestTwoPass(unittest.TestCase):
    def setUp(self):
        self.filename = Path("000100.mp4")
        self.target_filesize = 50.0  # MB

    @patch("ffmpeg4discord.twopass.ffmpeg.probe")
    def test_init(self, mock_probe: MagicMock):
        # Set up mock values for the probe
        mock_probe.return_value = {
            "streams": [
                {"index": 0, "codec_type": "video", "width": 1280, "height": 720},
                {"index": 1, "codec_type": "audio", "bit_rate": "128000"},
            ],
            "format": {"duration": "3600"},
        }

        # Create TwoPass instance
        twopass = TwoPass(self.filename, self.target_filesize)

        # Check attributes
        self.assertEqual(twopass.filename, self.filename)
        self.assertEqual(twopass.target_filesize, self.target_filesize)
        self.assertEqual(twopass.duration, 3600)
        self.assertEqual(twopass.audio_br, 128000)

    @patch("ffmpeg4discord.twopass.ffmpeg.probe")
    def test_time_from_file_name(self, mock_probe: MagicMock):
        # Set up mock values for the probe
        mock_probe.return_value = {
            "streams": [
                {"index": 0, "codec_type": "video", "width": 1280, "height": 720},
                {"index": 1, "codec_type": "audio", "bit_rate": "128000"},
            ],
            "format": {"duration": "3600"},
        }
        # mock_seconds_from_ts_string.return_value = 60

        # Create TwoPass instance
        twopass = TwoPass(self.filename, self.target_filesize)

        # Call time_from_file_name
        twopass.time_from_file_name()

        # Check attributes
        self.assertEqual(twopass.from_seconds, 60)
        self.assertEqual(twopass.times, {"ss": "00:01:00", "to": "01:00:00"})

    @patch("ffmpeg4discord.twopass.ffmpeg.probe")
    def test_create_bitrate_dict(self, mock_probe: MagicMock):
        # Set up mock values for the probe
        mock_probe.return_value = {
            "streams": [
                {"index": 0, "codec_type": "video", "width": 1280, "height": 720},
                {"index": 1, "codec_type": "audio", "bit_rate": "128000"},
            ],
            "format": {"duration": "120"},
        }

        # Create TwoPass instance
        twopass = TwoPass(self.filename, self.target_filesize)

        # Call create_bitrate_dict
        twopass.create_bitrate_dict()

        # Check bitrate_dict attribute
        self.assertEqual(twopass.bitrate_dict["b:v"], 3285000)
        self.assertEqual(twopass.bitrate_dict["minrate"], 1642500)
        self.assertEqual(twopass.bitrate_dict["maxrate"], 4763250)
        self.assertEqual(twopass.bitrate_dict["bufsize"], 6570000)

    @patch("ffmpeg4discord.twopass.os.path.getsize")
    @patch("ffmpeg4discord.twopass.ffmpeg.probe")
    @patch("ffmpeg4discord.twopass.ffmpeg.output")
    def test_run(self, mock_output: MagicMock, mock_probe: MagicMock, mock_os_path_getsize: MagicMock):
        # Set up mock values for the probe
        mock_probe.return_value = {
            "streams": [
                {"index": 0, "codec_type": "video", "width": 1280, "height": 720},
                {"index": 1, "codec_type": "audio", "bit_rate": "128000"},
            ],
            "format": {"duration": "3600"},
        }

        # Create TwoPass instance
        twopass = TwoPass(self.filename, self.target_filesize)

        # Mock output.run() to return some values
        mock_run = MagicMock()
        mock_run.run.return_value = ("a", "b")
        mock_output.return_value = mock_run
        mock_output.return_value.global_args.return_value = mock_run

        # Fake a file size
        mock_os_path_getsize.return_value = 52428799

        # Call run method
        result = twopass.run()

        # Check output_filesize attribute and return value
        self.assertLess(twopass.output_filesize, 50)  # Mocking output file size
        self.assertLess(result, 50)


if __name__ == "__main__":
    unittest.main()
