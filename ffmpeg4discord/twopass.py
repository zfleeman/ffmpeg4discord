import ffmpeg
import math
import logging
import json
import os
from datetime import datetime
from pathlib import Path

logging.getLogger().setLevel(logging.INFO)


class TwoPass:
    def __init__(
        self,
        filename: Path,
        target_filesize: float,
        output_dir: str = "",
        times: dict = {},
        audio_br: float = None,
        codec: str = "libx264",
        crop: str = "",
        resolution: str = "",
        config: str = "",
    ) -> None:
        """
        A Class to resize a video file to a specified MB target.
        This class utilizes ffmpeg's two-pass encoding technique with the
        ffmpeg-python wrapper package.
        https://trac.ffmpeg.org/wiki/Encode/H.264#twopass

        :param filename: video file that needs to be compressed
        :param output_dir: directory that the new, compressed output is delivered to
        :param times: dict containing "from" and "to" timestamp keys in the format 00:00:00
        :param target_filesize: desired file size of the output file, in MB
        :param audio_br: desired audio bitrate for the output file in kbps
        :param codec: ffmpeg video codec to use when encoding the file
        :param crop: coordinates for cropping the video to a different resolution
        :param resolution: output file's final resolution e.g. 1280x720
        :param config: json containing values for the above params
        """

        if config:
            self.init_from_config(config_file=config)
        else:
            self.target_filesize = target_filesize
            self.crop = crop
            self.resolution = resolution
            self.times = times
            self.audio_br = audio_br
            self.codec = codec

        self.filename = filename
        self.fname = filename.name
        self.split_fname = self.fname.split(".")
        self.output_dir = output_dir

        self.probe = ffmpeg.probe(filename=filename)
        self.duration = math.floor(float(self.probe["format"]["duration"]))

        if len(self.probe["streams"]) > 2:
            logging.warning(
                "This media file has more than two streams, which could cause errors during the encoding job."
            )

        for stream in self.probe["streams"]:
            ix = stream["index"]
            if stream["codec_type"] == "video":
                display_aspect_ratio = self.probe["streams"][ix]["display_aspect_ratio"].split(":")
                self.ratio = int(display_aspect_ratio[0]) / int(display_aspect_ratio[1])
            elif stream["codec_type"] == "audio":
                audio_stream = ix

        if not self.audio_br:
            self.audio_br = float(self.probe["streams"][audio_stream]["bit_rate"])
        else:
            self.audio_br = self.audio_br * 1000

        if self.times:
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
        else:
            self.time_from_file_name()

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

    def generate_params(self, codec: str):
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

    def time_from_file_name(self):
        """
        Create the -ss and -to fields from a file's name
        """
        fname = self.fname
        startstring = f"{fname[0:2]}:{fname[2:4]}:{fname[4:6]}"
        endstring = f"{fname[7:9]}:{fname[9:11]}:{fname[11:13]}"
        times = {}

        try:
            int(fname[0:6])
            self.from_seconds = seconds_from_ts_string(startstring)
            times["ss"] = startstring
            try:
                int(fname[11:13])
                self.to_seconds = seconds_from_ts_string(endstring)
                length = self.to_seconds - self.from_seconds
                times["to"] = endstring
            except:
                length = self.duration - self.from_seconds
                self.to_seconds = self.duration
        except:
            length = self.duration

        self.length = length
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

        self.output_filename = str(
            Path(self.output_dir)
            / ("small_" + self.filename.stem.replace(" ", "_") + datetime.strftime(datetime.now(), "_%Y%m%d%H%M%S.mp4"))
        )

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
