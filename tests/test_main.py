# pylint: disable=W0212, C0114, C0115, C0116, C0103
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import ffmpeg4discord.__main__ as mainmod


class TestMain(unittest.TestCase):
    def setUp(self) -> None:
        self.patcher_unlink = patch("pathlib.Path.unlink", return_value=None)
        self.patcher_resolve = patch("pathlib.Path.resolve", return_value=Path("output.mp4"))
        self.mock_unlink = self.patcher_unlink.start()
        self.mock_resolve = self.patcher_resolve.start()

    def tearDown(self) -> None:
        self.patcher_unlink.stop()
        self.patcher_resolve.stop()

    @patch("ffmpeg4discord.__main__.cleanup_files")
    def test_twopass_loop_approx(self, mock_cleanup: MagicMock) -> None:
        tp: MagicMock = MagicMock()
        tp.run.return_value = 5
        tp.output_filesize = 5
        tp.output_filename = "output.mp4"
        tp.target_filesize = 10
        tp.message = ""
        mainmod.twopass_loop(tp, target_filesize=10, approx=True)
        mock_cleanup.assert_called()
        self.assertIn("Your compressed video file", tp.message)

    @patch("ffmpeg4discord.__main__.cleanup_files")
    def test_twopass_loop_looping(self, mock_cleanup: MagicMock) -> None:
        _ = mock_cleanup
        tp: MagicMock = MagicMock()
        tp.run.side_effect = [15, 9]
        tp.output_filesize = 9
        tp.output_filename = "output.mp4"
        tp.target_filesize = 10
        tp.message = ""
        with patch("builtins.print") as mock_print:
            mainmod.twopass_loop(tp, target_filesize=10, approx=False)
        self.assertTrue(any("The output file size" in str(call) for call in mock_print.call_args_list))
        self.assertIn("Your compressed video file", tp.message)

    @patch("webbrowser.open")
    @patch("time.sleep")
    def test_open_browser(self, mock_sleep: MagicMock, mock_open: MagicMock) -> None:
        mainmod.open_browser(1234)
        mock_sleep.assert_called_once()
        mock_open.assert_called_once_with("http://localhost:1234")

    @patch("ffmpeg4discord.__main__.glob", return_value=["file1", "file2"])
    @patch("pathlib.Path.unlink")
    def test_cleanup_files(self, mock_unlink: MagicMock, mock_glob: MagicMock) -> None:
        _ = mock_glob
        mainmod.cleanup_files("pattern*")
        self.assertEqual(mock_unlink.call_count, 2)

    @patch("ffmpeg4discord.__main__.twopass_loop")
    @patch("ffmpeg4discord.__main__.TwoPass")
    @patch("ffmpeg4discord.__main__.arguments.get_args")
    def test_main_cli(self, mock_get_args: MagicMock, mock_TwoPass: MagicMock, mock_twopass_loop: MagicMock) -> None:
        args = {
            "web": False,
            "approx": False,
            "filename": "file.mp4",
            "target_filesize": 10,
            "audio_br": 96,
            "codec": "libx264",
            "vp9_opts": None,
            "filename_times": False,
            "crop": "",
            "resolution": "",
            "framerate": None,
            "output": "",
            "amix": False,
            "amix_normalize": False,
            "astreams": None,
        }
        mock_get_args.return_value = args.copy()
        tp: MagicMock = MagicMock()
        tp.message = "done"
        mock_TwoPass.return_value = tp
        with patch("builtins.print") as mock_print:
            mainmod.main()
        mock_twopass_loop.assert_called_once()
        mock_print.assert_called_with("done")

    @patch("ffmpeg4discord.__main__.twopass_loop")
    @patch("ffmpeg4discord.__main__.TwoPass")
    @patch("ffmpeg4discord.__main__.arguments.get_args")
    @patch("ffmpeg4discord.__main__.Flask")
    def test_main_web(
        self, mock_Flask: MagicMock, mock_get_args: MagicMock, mock_TwoPass: MagicMock, mock_twopass_loop: MagicMock
    ) -> None:
        _ = mock_twopass_loop
        args = {
            "web": True,
            "approx": True,
            "filename": "file.mp4",
            "target_filesize": 10,
            "audio_br": 96,
            "codec": "libx264",
            "vp9_opts": None,
            "filename_times": False,
            "crop": "",
            "resolution": "",
            "framerate": None,
            "output": "",
            "amix": False,
            "amix_normalize": False,
            "astreams": None,
            "port": 5000,
        }
        mock_get_args.return_value = args.copy()
        tp: MagicMock = MagicMock()
        mock_TwoPass.return_value = tp
        app: MagicMock = MagicMock()
        mock_Flask.return_value = app
        with patch("threading.Thread") as mock_thread:
            mainmod.main()
        mock_Flask.assert_called_once()
        mock_thread.assert_called_once()
        app.run.assert_called_once()

    @patch("pathlib.Path.resolve", return_value=Path("output.mp4"))
    @patch("pathlib.Path.unlink", return_value=None)
    @patch("ffmpeg4discord.__main__.twopass_loop")
    @patch("ffmpeg4discord.__main__.TwoPass")
    @patch("ffmpeg4discord.__main__.arguments.get_args")
    @patch("ffmpeg4discord.__main__.Flask")
    def test_main_web_run_args(
        self,
        mock_Flask: MagicMock,
        mock_get_args: MagicMock,
        mock_TwoPass: MagicMock,
        mock_twopass_loop: MagicMock,
        mock_unlink: MagicMock,
        mock_resolve: MagicMock,
    ) -> None:

        _ = mock_twopass_loop
        _ = mock_unlink
        _ = mock_resolve
        args = {
            "web": True,
            "approx": True,
            "filename": "file.mp4",
            "target_filesize": 10,
            "audio_br": 96,
            "codec": "libx264",
            "vp9_opts": None,
            "filename_times": False,
            "crop": "",
            "resolution": "",
            "framerate": None,
            "output": "",
            "amix": False,
            "amix_normalize": False,
            "astreams": None,
            "port": 5000,
        }
        mock_get_args.return_value = args.copy()
        tp: MagicMock = MagicMock()
        mock_TwoPass.return_value = tp
        app: MagicMock = MagicMock()
        mock_Flask.return_value = app
        with patch("threading.Thread") as mock_thread:
            mainmod.main()
        mock_Flask.assert_called_once()
        mock_thread.assert_called_once()
        app.run.assert_called_once_with("0.0.0.0", port=5000)


if __name__ == "__main__":
    unittest.main()
