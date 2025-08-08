"""
This module provides the TwoPass class and utility functions for performing two-pass video encoding using FFmpeg.

The TwoPass class allows users to compress video files to a specified target file size while maintaining
optimal video quality. It supports various encoding parameters such as codec, resolution, and audio bitrate.
The module also includes helper functions for timestamp conversion.

Classes:
- TwoPass: Encodes and resizes video files using FFmpeg's two-pass encoding to meet a specified target file size.

Functions:
- seconds_from_ts_string: Converts a timestamp string into an integer representing seconds.
- seconds_to_timestamp: Converts an integer representing seconds into a timestamp string.
"""

import logging
import math
import os
from datetime import datetime
from pathlib import Path
from textwrap import dedent
from typing import Optional

import ffmpeg

logging.getLogger().setLevel(logging.INFO)


class TwoPass:
    """
    Encodes and resizes video files using ffmpeg's two-pass encoding to meet a specified target file size.

    The TwoPass class leverages the ffmpeg-python library to compress video files while allowing control
    over attributes such as codec, resolution, and target file size. It performs two-pass encoding
    to achieve optimal video quality at the desired size.

    Two-Pass encoding documentation: https://trac.ffmpeg.org/wiki/Encode/H.264#twopass

    Attributes:
        filename (Path): Path to the input video file that needs compression.
        target_filesize (float): Desired target filesize in megabytes (MB).
        output (str): Output file path or directory where the compressed video will be saved.
        times (dict): Dictionary with keys "from" and "to" specifying timestamps (in seconds) for encoding a segment.
        audio_br (float): Audio bitrate in kilobits per second (kbps), if specified. Defaults to automatic calculation.
        codec (str): Video codec to use for compression, e.g., 'libx264' (default).
        crop (str): Crop settings (if any) for the video.
        resolution (str): Target resolution for the output video.
        filename_times (bool): Flag to include timestamps in the output filename.
        verbose (bool): Flag to allow verbose logging
        vp9_opts (dict): JSON string to configure row-mt, deadline, and cpu-used options for VP9 encoding.
    """

    def __init__(
        self,
        filename: Path,
        target_filesize: float,
        output: str = "",
        times: Optional[dict] = None,
        audio_br: Optional[float] = None,
        codec: str = "libx264",
        crop: str = "",
        resolution: str = "",
        filename_times: bool = False,
        verbose: bool = False,
        framerate: Optional[int] = None,
        vp9_opts: Optional[dict] = None,
    ) -> None:

        self.target_filesize = target_filesize
        self.crop = crop
        self.resolution = resolution
        self.times = times or {}
        self.audio_br = audio_br
        self.codec = codec
        self.framerate = framerate
        self.output = output
        self.vp9_opts = vp9_opts or {}
        self.verbose = verbose
        self.output_filename = ""
        self.output_filesize = 0
        self.bitrate_dict = {}
        self.message = ""

        self.filename = filename
        self.fname = filename.name
        self.split_fname = self.fname.split(".")

        # Attributes set/updated by helper methods
        self.duration = None
        self.ratio = None
        self.init_framerate = None
        self.from_seconds = None
        self.to_seconds = None
        self.length = None

        # create a Path from the output string
        self.output = Path(self.output).resolve()

        self.probe = ffmpeg.probe(filename=filename)
        self._process_probe()
        self._process_times(filename_times)

    def _parse_streams(self):
        """
        Helper to parse video and audio streams from the probe output.
        Sets self.ratio, self.init_framerate, and returns audio_stream index.
        """
        audio_stream = None
        for stream in self.probe["streams"]:
            codec_type = stream["codec_type"]
            if codec_type == "video":
                width = stream["width"]
                height = stream["height"]
                self.ratio = width / height
                framerate_ratio: str = stream.get("r_frame_rate")
                self.init_framerate = round(int(framerate_ratio.split("/")[0]) / int(framerate_ratio.split("/")[1]))
            elif codec_type == "audio":
                audio_stream = stream["index"]
        return audio_stream

    def _process_probe(self):
        """
        Processes the ffmpeg probe output to set duration, ratio, framerate, and audio bitrate attributes.
        """
        # set the total video duration -- for use throughout the call and the web ui
        self.duration = math.floor(float(self.probe["format"]["duration"]))

        if len(self.probe["streams"]) > 2:
            logging.warning(
                "This media file has more than two streams, which could cause errors during the encoding job."
            )

        audio_stream = self._parse_streams()

        if audio_stream is not None:
            if not self.audio_br:
                self.audio_br = float(self.probe["streams"][audio_stream]["bit_rate"])
            else:
                self.audio_br = self.audio_br * 1000
        else:
            logging.warning("No audio stream found in the media file.")

    def _process_times(self, filename_times: bool):
        """
        Handles the logic for setting up trimming times and related attributes.
        """
        # times are supplied by the file's name
        if filename_times:
            self._time_from_file_name()

        # times are provided by the flags or config file
        elif self.times:
            if self.times.get("from"):
                self.times["ss"] = self.times["from"] or "00:00:00"
                self.times.pop("from", None)
            else:
                self.times["ss"] = "00:00:00"

            self.from_seconds = seconds_from_ts_string(self.times["ss"])

            if self.times.get("to"):
                self.to_seconds = seconds_from_ts_string(self.times["to"])
                self.length = self.to_seconds - self.from_seconds
            else:
                self.length = self.duration - self.from_seconds
                self.times["to"] = seconds_to_timestamp(self.duration)

        # no trimming times were provided
        else:
            self.times = {"ss": "00:00:00", "to": seconds_to_timestamp(self.duration)}
            self.length = self.duration

        if self.length <= 0:
            raise ValueError(
                dedent(
                    f"""\033[31m
                    Time Paradox?

                    Something is wrong with your clipping times. Use this
                    information to further diagnose the problem:

                    - Your video is {self.duration / 60} minutes long
                    - Your clipping times are {self.times}
                    \033[0m"""
                )
            )

    def _generate_params(self, codec: str) -> dict:
        """
        Create params for the ffmpeg.output() function
        :param codec: ffmpeg video codec to use during encoding
        :return: dictionary containing parameters for ffmpeg's first and second pass.
        """

        params = {
            "pass1": {
                "pass": 1,
                "f": "null",
                "vsync": "cfr",  # not sure if this is unique to x264 or not
                "c:v": codec,
            },
            "pass2": {"pass": 2, "b:a": self.audio_br, "c:v": codec},
        }

        # assign the output framerate
        if self.framerate:
            if self.framerate < self.init_framerate:
                params["pass1"]["r"] = self.framerate
                params["pass2"]["r"] = self.framerate
            else:
                logging.warning(
                    dedent(
                        f"""\033[31m
                        Desired framerate ({self.framerate}) is more than original framerate ({self.init_framerate}).
                        Keeping the original framerate...
                        \033[0m"""
                    )
                )

        if codec == "libx264":
            params["pass2"]["c:a"] = "aac"
        elif codec == "libvpx-vp9":
            row_mt = self.vp9_opts.get("row-mt", 1)
            cpu_used = self.vp9_opts.get("cpu-used", 2)
            deadline = self.vp9_opts.get("deadline", "good")

            params["pass1"]["row-mt"] = row_mt
            params["pass2"]["row-mt"] = row_mt
            params["pass2"]["cpu-used"] = cpu_used
            params["pass2"]["deadline"] = deadline
            params["pass2"]["c:a"] = "libopus"

        params["pass1"].update(**self.bitrate_dict)
        params["pass2"].update(**self.bitrate_dict)

        return params

    def _create_bitrate_dict(self) -> None:
        """
        Perform the calculation specified in ffmpeg's documentation that generates
        the video bitrates needed to achieve the target file size
        """
        br = math.floor((self.target_filesize * 8192) / self.length - (self.audio_br / 1000)) * 1000
        self.bitrate_dict = {
            "b:v": br,
            "minrate": br * 0.5,
            "maxrate": br * 1.45,
            "bufsize": br * 2,
        }

    def _time_from_file_name(self):
        """
        Extracts start (`-ss`) and optional end (`-to`) timestamps from the file name and updates the instance's
        time-related attributes. Assumes the file name is in one of two formats:
        - 'HHMMSS' (start time only)
        - 'HHMMSS-HHMMSS' (start and end times)

        If the end time is not provided, the function defaults the end time to the full video duration.
        """
        fname = self.fname
        times = {}

        try:
            # Parse start time from the first six characters
            start_time_str = f"{fname[0:2]}:{fname[2:4]}:{fname[4:6]}"
            self.from_seconds = seconds_from_ts_string(start_time_str)
            times["ss"] = start_time_str

            # Check if there is an additional six digits for end time
            if len(fname) > 6 and fname[7:13].isdigit():
                end_time_str = f"{fname[7:9]}:{fname[9:11]}:{fname[11:13]}"
                self.to_seconds = seconds_from_ts_string(end_time_str)
                times["to"] = end_time_str
                self.length = self.to_seconds - self.from_seconds
            else:
                # Default to the full duration if end time is not provided
                times["to"] = seconds_to_timestamp(self.duration)
                self.length = self.duration - self.from_seconds
                self.to_seconds = self.duration

        except ValueError:
            # Handle any issues with timestamp parsing by defaulting to full duration
            self.length = self.duration
            times = {"ss": "00:00:00", "to": seconds_to_timestamp(self.duration)}
            logging.warning("Warning: Invalid time format in filename. Defaulting to full duration.")

        # Update instance attributes with calculated times
        self.times = times

    def _apply_video_filters(self, video):
        """
        Function to apply the crop and resolution parameters to a video object
        :param video: the ffmpeg video object from the Class's input video file
        :return: the video object after it has been cropped or resized
        """

        if self.crop:
            crop = self.crop.split("x")
            video = video.crop(x=crop[0], y=crop[1], width=crop[2], height=crop[3])
            self.ratio = int(crop[2]) / int(crop[3])

        if self.resolution:
            video = video.filter("scale", self.resolution)
            x = int(self.resolution.split("x")[0])
            y = int(self.resolution.split("x")[1])
            outputratio = x / y

            if self.ratio != outputratio:
                logging.warning(
                    dedent(
                        """\033[31m
                        Your output resolution's aspect ratio does not match the
                        input resolution's or your croped resolution's aspect ratio.
                        \033[0m"""
                    )
                )

        return video

    def run(self) -> float:
        """
        Perform the CPU-intensive encoding job
        :return: the output file's size
        """

        ext: str = ".webm" if self.codec == "libvpx-vp9" else ".mp4"
        if self.output.is_dir():
            self.output_filename = str(
                self.output
                / (
                    "small_"
                    + self.filename.stem.replace(" ", "_")
                    + datetime.strftime(datetime.now(), f"_%Y%m%d%H%M%S{ext}")
                )
            )
        else:
            if ext != self.output.suffix:
                logging.warning(
                    dedent(
                        f"""\033[31m
                        You specified {self.codec}, but your output file name ends with {self.output.suffix}.
                        I've corrected this.
                        \033[0m"""
                    )
                )

                # correct the file suffix
                if self.codec == "libvpx-vp9":
                    self.output = self.output.with_suffix(".webm")
                else:
                    self.output = self.output.with_suffix(".mp4")

            self.output_filename = str(self.output)

        # generate run parameters
        self._create_bitrate_dict()
        params = self._generate_params(codec=self.codec)

        # separate streams from ffinput
        ffinput = ffmpeg.input(self.filename, **self.times)
        video = self._apply_video_filters(ffinput.video)
        audio = ffinput.audio

        # set our logging level
        loglevel = "quiet" if not self.verbose else "verbose"

        # First Pass
        ffoutput = ffmpeg.output(video, "pipe:", **params["pass1"])
        ffoutput = ffoutput.global_args("-loglevel", loglevel, "-stats")
        print("Performing first pass")
        _, _ = ffoutput.run(capture_stdout=True)

        # Second Pass
        ffoutput = ffmpeg.output(video, audio, self.output_filename, **params["pass2"])
        ffoutput = ffoutput.global_args("-loglevel", loglevel, "-stats")
        print("\nPerforming second pass")
        ffoutput.run(overwrite_output=True)

        # save the output file size and return it
        self.output_filesize = os.path.getsize(self.output_filename) * 0.00000095367432

        return self.output_filesize


def seconds_from_ts_string(ts_string: str) -> int:
    """
    Take a "timestamp string" and convert it into an integer in seconds
    """
    return int(ts_string[0:2]) * 60 * 60 + int(ts_string[3:5]) * 60 + int(ts_string[6:8])


def seconds_to_timestamp(seconds: int) -> str:
    """
    Take seconds (as an integer) and convert it into a "timestamp string"
    """
    hours, remainder = divmod(seconds, 3600)
    minutes, seconds = divmod(remainder, 60)

    # Use f-strings to format the timestamp
    timestamp = f"{hours:02d}:{minutes:02d}:{seconds:02d}"

    return timestamp
