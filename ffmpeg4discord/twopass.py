import json
import logging
import math
import os

from datetime import datetime
from pathlib import Path
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
        config (str): Path to an optional configuration file for advanced ffmpeg settings.
        filename_times (bool): Flag to include timestamps in the output filename.
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
        config: Optional[str] = None,
        filename_times: bool = False,
    ) -> None:
        if config:
            self.init_from_config(config_file=config)
        else:
            self.target_filesize = target_filesize
            self.crop = crop
            self.resolution = resolution
            self.times = times or {}
            self.audio_br = audio_br
            self.codec = codec

        self.filename = filename
        self.fname = filename.name
        self.split_fname = self.fname.split(".")
        self.output = Path(output).resolve()

        self.probe = ffmpeg.probe(filename=filename)
        self.duration = math.floor(float(self.probe["format"]["duration"]))

        if len(self.probe["streams"]) > 2:
            logging.warning(
                "This media file has more than two streams, which could cause errors during the encoding job."
            )

        for stream in self.probe["streams"]:
            ix = stream["index"]
            codec_type = stream["codec_type"]
            if codec_type == "video":
                width = self.probe["streams"][ix]["width"]
                height = self.probe["streams"][ix]["height"]
                self.ratio = width / height
            elif codec_type == "audio":
                audio_stream = ix

        if not self.audio_br:
            self.audio_br = float(self.probe["streams"][audio_stream]["bit_rate"])
        else:
            self.audio_br = self.audio_br * 1000

        # times are supplied by the file's name
        if filename_times:
            self.time_from_file_name()

        # times are provided by the flags or config file
        elif self.times:
            if self.times.get("from"):
                self.times["ss"] = self.times["from"] or "00:00:00"
                del self.times["from"]
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
            raise Exception(
                f"""
                Time Paradox?

                Something is wrong with your clipping times. Use this
                information to further diagnose the problem:

                - Your video is {self.duration / 60} minutes long
                - Your clipping times are {self.times}
                """
            )

    def init_from_config(self, config_file: str) -> None:
        """
        Set the Class values from a json file
        :param config_file: path to a json file containing parameters for TwoPass()
        """
        file_path = Path(config_file).resolve()
        with open(file_path) as f:
            config = json.load(f)
        self.__dict__.update(**config)

    def generate_params(self, codec: str) -> dict:
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

        if codec == "libx264":
            params["pass2"]["c:a"] = "aac"
        elif codec == "libvpx-vp9":
            params["pass1"]["row-mt"] = 1
            params["pass2"]["row-mt"] = 1
            params["pass2"]["cpu-used"] = 2
            params["pass2"]["deadline"] = "good"
            params["pass2"]["c:a"] = "libopus"

        params["pass1"].update(**self.bitrate_dict)
        params["pass2"].update(**self.bitrate_dict)

        return params

    def create_bitrate_dict(self) -> None:
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

    def time_from_file_name(self) -> dict:
        """
        Extracts start (`-ss`) and end (`-to`) timestamps from the file name and updates the instance's
        time-related attributes. Assumes the file name contains time codes in the format 'HHMMSS-HHMMSS'.

        This method calculates `from_seconds` and `to_seconds` from the filename and adjusts the duration
        accordingly if the end time is missing. Updates the `self.times` dictionary with `-ss` and `-to` values
        and computes `self.length`.
        """
        fname = self.fname
        times = {}

        try:
            # Parse start time from filename
            start_time_str = f"{fname[0:2]}:{fname[2:4]}:{fname[4:6]}"
            self.from_seconds = seconds_from_ts_string(start_time_str)
            times["ss"] = start_time_str

            # Parse end time from filename if it exists
            end_time_str = f"{fname[7:9]}:{fname[9:11]}:{fname[11:13]}"
            if fname[7:13].isdigit():
                self.to_seconds = seconds_from_ts_string(end_time_str)
                times["to"] = end_time_str
                self.length = self.to_seconds - self.from_seconds
            else:
                # If end time is missing, set `to` to video duration
                times["to"] = seconds_to_timestamp(self.duration)
                self.length = self.duration - self.from_seconds
                self.to_seconds = self.duration

        except ValueError:
            # If parsing fails, default length to full duration
            self.length = self.duration

        # Update time dictionary
        self.times = times

    def apply_video_filters(self, video):
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
                    """
                    Your output resolution's aspect ratio does not match the
                    input resolution's or your croped resolution's aspect ratio.
                    """
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
                    f"You specified {self.codec}, but your output file name ends with {self.output.suffix}. I've corrected this."
                )

                # correct the file suffix
                if self.codec == "libvpx-vp9":
                    self.output = self.output.with_suffix(".webm")
                else:
                    self.output = self.output.with_suffix(".mp4")

            self.output_filename = str(self.output)

        # generate run parameters
        self.create_bitrate_dict()
        params = self.generate_params(codec=self.codec)

        # separate streams from ffinput
        ffinput = ffmpeg.input(self.filename, **self.times)
        video = self.apply_video_filters(ffinput.video)
        audio = ffinput.audio

        # First Pass
        ffOutput = ffmpeg.output(video, "pipe:", **params["pass1"])
        ffOutput = ffOutput.global_args("-loglevel", "quiet", "-stats")
        print("Performing first pass")
        std_out, std_err = ffOutput.run(capture_stdout=True)

        # Second Pass
        ffOutput = ffmpeg.output(video, audio, self.output_filename, **params["pass2"])
        ffOutput = ffOutput.global_args("-loglevel", "quiet", "-stats")
        print("\nPerforming second pass")
        ffOutput.run(overwrite_output=True)

        # save the output file size and return it
        self.output_filesize = os.path.getsize(self.output_filename) * 0.00000095367432

        return self.output_filesize


def seconds_from_ts_string(ts_string: str):
    return int(ts_string[0:2]) * 60 * 60 + int(ts_string[3:5]) * 60 + int(ts_string[6:8])


def seconds_to_timestamp(seconds: int) -> str:
    hours, remainder = divmod(seconds, 3600)
    minutes, seconds = divmod(remainder, 60)

    # Use f-strings to format the timestamp
    timestamp = f"{hours:02d}:{minutes:02d}:{seconds:02d}"

    return timestamp
