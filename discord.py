import ffmpeg
import math
import os
from datetime import datetime
from typing import Tuple
from utils.arguments import get_args, Namespace


class Encoder:

    def __init__(self, args: Namespace) -> None:
        self.filename = args.filename
        self.fname = args.filename.replace("\\", "/").split("/")[-1]
        self.split_fname = self.fname.split(".")

        self.output_filename = (
            args.output
            + "small_"
            + self.split_fname[0].replace(" ", "_")
            + datetime.strftime(datetime.now(), "_%Y%m%d%H%M%S.mp4")
        )

        self.target_fs = args.filesize
        self.file_info = self.probe() # function instead of setting
        self.input_ratio = self.file_info["streams"][0]["width"] / self.file_info["streams"][0]["height"] # function instead of setting
        self.duration = math.floor(float(self.file_info["format"]["duration"]))

        self.time_calculations()


    def probe(self) -> dict:
        '''
        ffprobe method for the class
        :return: ffprobe dict
        '''
        return ffmpeg.probe(filename=self.filename)

    def get_bitrate(self, length, filesize, audio_br) -> Tuple[float, float, float]:
        br = math.floor(filesize / length - audio_br) * 1000
        return br, br * 0.50, br * 1.45

    def time_calculations(self):
        fname = self.fname
        startstring = fname[0:2] + ":" + fname[2:4] + ":" + fname[4:6]
        endstring = fname[7:9] + ":" + fname[9:11] + ":" + fname[11:13]
        times = {}

        try:
            int(fname[0:6])
            startseconds = (
                int(fname[0:2]) * 60 * 60 + int(fname[2:4]) * 60 + int(fname[4:6])
            )
            times["ss"] = startstring
            try:
                int(fname[11:13])
                endseconds = (
                    int(fname[7:9]) * 60 * 60 + int(fname[9:11]) * 60 + int(fname[11:13])
                )
                length = endseconds - startseconds
                times["to"] = endstring
            except:
                length = self.duration - startseconds
        except:
            length = self.duration

        self.length = length
        self.times = times


    def apply_video_filters(self, ffInput):
        video = ffInput.video

        if args.crop:
            crop = args.crop.split("x")
            video = video.crop(x=crop[0], y=crop[1], width=crop[2], height=crop[3])
            args.inputratio = int(crop[2]) / int(crop[3])

        if args.resolution:
            video = video.filter("scale", args.resolution)
            x = int(args.resolution.split("x")[0])
            y = int(args.resolution.split("x")[1])
            outputratio = x / y

            if args.inputratio != outputratio:
                print("!!!!!!!!!\n!WARNING!\n!!!!!!!!!")
                print(
                    "Your output resolution's aspect ratio does not match the\ninput resolution's or your croped resolution's aspect ratio."
                )

        return video


    def first_pass(self, params, times):
        ffInput = ffmpeg.input(self.filename, **times)
        video = self.apply_video_filters(ffInput)
        ffOutput = ffmpeg.output(video, "pipe:", **params)
        ffOutput = ffOutput.global_args("-loglevel", "quiet", "-stats")
        std_out, std_err = ffOutput.run(capture_stdout=True)


    def second_pass(self, params, times):
        ffInput = ffmpeg.input(self.filename, **times)
        audio = ffInput.audio
        video = self.apply_video_filters(ffInput)
        ffOutput = ffmpeg.output(video, audio, self.output_filename, **params)
        ffOutput = ffOutput.global_args("-loglevel", "quiet", "-stats")
        ffOutput.run(overwrite_output=True)


    def get_new_fs(self, target_fs):
        return target_fs <= os.path.getsize(self.output_filename) * 0.00000095367432

if __name__ == "main":

    args = get_args()
    job = Encoder(args)

    if job.length <= 0:
        raise Exception(
            f"Your video is {job.duration / 60} minutes long, but you wanted to start clpping at {job.times['ss']}"
        )

    run = True

    while run:
        end_fs = args.filesize * 8192
        br, minbr, maxbr = job.get_bitrate(
            length=job.length, filesize=end_fs, audio_br=args.audio_br
        )

        pass_one_params = {
            "pass": 1,
            "f": "null",
            "vsync": "cfr",
            "c:v": "libx264",
            "b:v": br,
            "minrate": minbr,
            "maxrate": maxbr,
            "bufsize": br * 2,
        }

        pass_two_params = {
            "pass": 2,
            "c:v": "libx264",
            "c:a": "aac",
            "b:a": args.audio_br * 1000,
            "b:v": br,
            "minrate": minbr,
            "maxrate": maxbr,
            "bufsize": br * 2,
        }

        print("Performing first pass.")
        job.first_pass(pass_one_params, job.times)
        print("First pass complete.\n")

        print("Performing second pass.")
        job.second_pass(pass_two_params, job.times)
        print("Second pass complete.\n")

        run = job.get_new_fs(job.target_fs)

        if run:
            print(
                f"Resultant file size still above the target of {job.target_fs}MB.\nRestarting...\n"
            )
            os.remove(job.output_filename)
            args.filesize -= 0.2
        else:
            print(f"Smaller file located at {job.output_filename}")
