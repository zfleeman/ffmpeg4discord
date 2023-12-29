import ffmpeg
import math
import logging
import json
from datetime import datetime

logging.getLogger().setLevel(logging.INFO)


class TwoPass:
    def __init__(
        self,
        filename: str,
        output_dir: str,
        filesize: float = 8.0,
        audio_br: float = 96,
        crop: str = "",
        resolution: str = "",
        config_file: str = "",
    ) -> None:
        self.filename = filename
        self.output_dir = output_dir

        if config_file:
            self.init_from_config(config_file=config_file)
        else:
            self.filesize = filesize
            self.audio_br = audio_br
            self.crop = crop
            self.resolution = resolution

        self.fname = self.filename.replace("\\", "/").split("/")[-1]
        self.split_fname = self.fname.split(".")

        self.output_filename = (
            self.output_dir
            + "small_"
            + self.split_fname[0].replace(" ", "_")
            + datetime.strftime(datetime.now(), "_%Y%m%d%H%M%S.mp4")
        )

        self.target_fs = self.filesize
        self.probe()
        self.input_ratio = self.file_info["streams"][0]["width"] / self.file_info["streams"][0]["height"]
        self.duration = math.floor(float(self.file_info["format"]["duration"]))

        self.time_calculations()

        bitrate_dict = self.get_bitrate()

        self.pass_one_params = {
            "pass": 1,
            "f": "null",
            "vsync": "cfr",
            "c:v": "libx264",
        }
        self.pass_one_params.update(**bitrate_dict)

        self.pass_two_params = {
            "pass": 2,
            "c:v": "libx264",
            "c:a": "aac",
            "b:a": self.audio_br * 1000,
        }
        self.pass_two_params.update(**bitrate_dict)

    def init_from_config(self, config_file: str) -> None:
        with open(config_file) as f:
            config = json.load(f)
        self.__dict__.update(**config)

    def probe(self) -> None:
        self.file_info = ffmpeg.probe(filename=self.filename)

    def get_bitrate(self, filesize=None) -> float:
        if not filesize:
            filesize = self.filesize
        br = math.floor(filesize / self.length - self.audio_br) * 1000
        br_dict = {
            "b:v": br,
            "minrate": br * 0.5,
            "maxrate": br * 1.45,
            "bufsize": br * 2,
        }
        return br_dict

    def time_calculations(self):
        fname = self.fname
        startstring = fname[0:2] + ":" + fname[2:4] + ":" + fname[4:6]
        endstring = fname[7:9] + ":" + fname[9:11] + ":" + fname[11:13]
        times = {}

        try:
            int(fname[0:6])
            startseconds = int(fname[0:2]) * 60 * 60 + int(fname[2:4]) * 60 + int(fname[4:6])
            times["ss"] = startstring
            try:
                int(fname[11:13])
                endseconds = int(fname[7:9]) * 60 * 60 + int(fname[9:11]) * 60 + int(fname[11:13])
                length = endseconds - startseconds
                times["to"] = endstring
            except:
                length = self.duration - startseconds
        except:
            length = self.duration

        if length <= 0:
            raise Exception(
                f"Your video is {self.duration / 60} minutes long, but you wanted to start clpping at {self.times['ss']}"
            )

        self.length = length
        self.times = times

    def apply_video_filters(self, ffInput):
        video = ffInput.video

        if self.crop:
            crop = self.crop.split("x")
            video = video.crop(x=crop[0], y=crop[1], width=crop[2], height=crop[3])
            self.inputratio = int(crop[2]) / int(crop[3])

        if self.resolution:
            video = video.filter("scale", self.resolution)
            x = int(self.resolution.split("x")[0])
            y = int(self.resolution.split("x")[1])
            outputratio = x / y

            if self.inputratio != outputratio:
                logging.warning(
                    "Your output resolution's aspect ratio does not match the\ninput resolution's or your croped resolution's aspect ratio."
                )

        return video

    def first_pass(self, params=None):
        if not params:
            params = self.pass_one_params
        ffInput = ffmpeg.input(self.filename, **self.times)
        video = self.apply_video_filters(ffInput)
        ffOutput = ffmpeg.output(video, "pipe:", **params)
        ffOutput = ffOutput.global_args("-loglevel", "quiet", "-stats")
        std_out, std_err = ffOutput.run(capture_stdout=True)

    def second_pass(self, params=None):
        if not params:
            params = self.pass_one_params
        ffInput = ffmpeg.input(self.filename, **self.times)
        audio = ffInput.audio
        video = self.apply_video_filters(ffInput)
        ffOutput = ffmpeg.output(video, audio, self.output_filename, **params)
        ffOutput = ffOutput.global_args("-loglevel", "quiet", "-stats")
        ffOutput.run(overwrite_output=True)
