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
        target_filesize: float,
        audio_br: float = 96,
        codec: str = "libx264",
        crop: str = "",
        resolution: str = "",
        config_file: str = "",
    ) -> None:
        self.codec = codec
        self.filename = filename
        self.file_info = ffmpeg.probe(filename=self.filename)
        self.output_dir = output_dir

        if config_file:
            self.init_from_config(config_file=config_file)
        else:
            self.target_filesize = target_filesize
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

        self.input_ratio = self.file_info["streams"][0]["width"] / self.file_info["streams"][0]["height"]
        self.duration = math.floor(float(self.file_info["format"]["duration"]))
        self.time_calculations()

    def init_from_config(self, config_file: str) -> None:
        with open(config_file) as f:
            config = json.load(f)
        self.__dict__.update(**config)

    def generate_params(self, codec: str):
        params = {
            "pass1": {
                "pass": 1,
                "f": "null",
                "vsync": "cfr",  # not sure if this is unique to x264 or not
                "c:v": codec,
            },
            "pass2": {"pass": 2, "b:a": self.audio_br * 1000, "c:v": codec},
        }

        if codec == "libx264":
            params["pass2"]["c:a"] = "aac"
        elif codec == "vp9":
            # still a lot of work here
            params["pass2"]["c:a"] = "libopus"

        params["pass1"].update(**self.bitrate_dict)
        params["pass2"].update(**self.bitrate_dict)

        return params

    def create_bitrate_dict(self) -> None:
        br = math.floor((self.target_filesize * 8192) / self.length - self.audio_br) * 1000
        bitrate_dict = {
            "b:v": br,
            "minrate": br * 0.5,
            "maxrate": br * 1.45,
            "bufsize": br * 2,
        }
        self.bitrate_dict = bitrate_dict

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

    def apply_video_filters(self, ffinput):
        video = ffinput.video

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

    def run(self):
        # generate run parameters
        self.create_bitrate_dict()
        params = self.generate_params(codec=self.codec)

        # separate streams from ffinput
        ffinput = ffmpeg.input(self.filename, **self.times)
        video = self.apply_video_filters(ffinput)
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
