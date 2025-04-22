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
import shutil
import subprocess 
from datetime import datetime
from pathlib import Path
from textwrap import dedent
from typing import Optional, List

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
        amerge (bool): Flag to enable audio downmixing post-encoding.
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
        amerge: bool = False, 
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
        self.amerge = amerge

        self.filename = filename
        self.fname = filename.name
        self.split_fname = self.fname.split(".")

        # create a Path from the output string
        self.output = Path(self.output).resolve()

        self.probe = ffmpeg.probe(filename=filename)
        self.duration = math.floor(float(self.probe["format"]["duration"]))

        if len(self.probe["streams"]) > 2:
            logging.warning(
                "This media file has more than two streams, which could cause errors during the encoding job."
            )

        # Extract some information from the probe.
        audio_stream = None
        for stream in self.probe["streams"]:
            ix = stream["index"]
            codec_type = stream["codec_type"]
            if codec_type == "video":
                width = self.probe["streams"][ix]["width"]
                height = self.probe["streams"][ix]["height"]
                self.ratio = width / height

                # Get the framerate for later comparisons
                framerate_ratio: str = self.probe["streams"][ix].get("r_frame_rate")
                self.init_framerate = round(int(framerate_ratio.split("/")[0]) / int(framerate_ratio.split("/")[1]))

            elif codec_type == "audio":
                audio_stream = ix

        if audio_stream is not None:
            if not self.audio_br:
                self.audio_br = float(self.probe["streams"][audio_stream]["bit_rate"])
            else:
                self.audio_br = self.audio_br * 1000
        else:
            logging.warning("No audio stream found in the media file.")

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
            self.times = {"ss": "00:00:00", "to": seconds_to_timestamp(self.duration)}
            logging.warning("Warning: Invalid time format in filename. Defaulting to full duration.")

        # Update instance attributes with calculated times
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
        self.create_bitrate_dict()
        params = self.generate_params(codec=self.codec)

        # separate streams from ffinput
        ffinput = ffmpeg.input(self.filename, **self.times)
        video = self.apply_video_filters(ffinput.video)
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

    def downmix_audio(self) -> bool:
        """
        Performs audio downmixing to mono on the already encoded output file using
        a manually constructed command with subprocess.run() to ensure correct syntax.
        This should be called *after* the `run()` method succeeds.

        Replaces the original output file with the downmixed version if successful.
        Updates `self.output_filesize` and `self.message`.

        Returns:
            bool: True if downmixing was successful or not needed/skipped, False otherwise.
        """

        output_path = Path(self.output_filename)
        print(f"\n--- Starting Mono Audio Downmix (using subprocess.run) for {output_path.name} ---")
        
        # --- Probe the intermediate file to count audio streams and channels ---
        # Initialize variables to store probe results
        audio_streams: List[dict] = []
        num_audio_streams = 0
        total_input_channels = 0
        
        logging.info(f"Probing intermediate file for audio streams: {output_path}")
        # Call ffprobe (via ffmpeg-python) to get stream info
        intermediate_probe = ffmpeg.probe(str(output_path))
        # Filter the streams to get only the audio ones
        audio_streams = [s for s in intermediate_probe.get("streams", []) if s.get("codec_type") == "audio"]
        # Count how many audio streams were found
        num_audio_streams = len(audio_streams)

        # If no audio streams, skip downmixing
        if num_audio_streams == 0:
            logging.warning("No audio streams found in the intermediate file. Skipping downmix.")
            return True
        
        # Loop through the found audio streams to count total channels
        for stream in audio_streams:
            total_input_channels += int(stream.get('channels', 0))

        # Skip if the audio is already effectively mono or has zero channels
        if total_input_channels == 0:
                logging.warning("Intermediate file audio stream(s) report 0 total channels. Skipping downmix.")
                return True
        elif total_input_channels == 1:
                logging.info("Intermediate file already has a single mono audio channel total. Skipping downmix.")
                return True
        else:
                logging.info(f"Detected {num_audio_streams} audio stream(s) with {total_input_channels} total channels. Proceeding with merge and downmix.")

  
        # Create a temporary filename for the downmixed output
        temp_output_filename = str(output_path.with_name(output_path.stem + "_mono_temp" + output_path.suffix))
        # Revert to warning? No, keep verbose toggle
        loglevel = "verbose" if self.verbose else "warning" 
        # Determine the target audio codec based on the video codec used
        audio_codec = "aac" if self.codec == "libx264" else "libopus"
        # Calculate the target audio bitrate in bits per second (from kbps stored in self.audio_br)
        audio_br_bps = self.audio_br * 1000 if self.audio_br is not None else 0
        # Format the bitrate as a string argument for ffmpeg, or None if bitrate is 0
        audio_bitrate_param = f"{int(audio_br_bps)}" if audio_br_bps > 0 else None
       
        # Manually construct the command arguments list for subprocess.run()
        # Initialize variable for the command execution block
        cmd = []
        # Calculate the number of channels after amerge (should equal total_input_channels)
        num_merged_channels = total_input_channels
        # Calculate the coefficient for averaging all channels (1 / total channels)
        coeff = 1.0 / num_merged_channels
        # Create the coefficient string for the pan filter (e.g., "0.125*c0+0.125*c1+...+0.125*c7" for 8 channels)
        pan_coeffs = "+".join([f"{coeff:.3f}*c{i}" for i in range(num_merged_channels)])

        # Construct the full filter_complex string
        filter_complex_str = f"[0:a]amerge=inputs={num_audio_streams}[a_merged];[a_merged]pan=mono|c0={pan_coeffs}[a_out]"
        logging.info(f"Using filter_complex: {filter_complex_str}")

        # Build the command as a list of strings
        cmd = [
            'ffmpeg',
            # Global Option: Prevents FFmpeg from trying to read interactive input from the console.
            '-nostdin', 
            # Input Option: Specifies the input file. `-i` is the flag, and `str(output_path)` is the path to the intermediate 
            # video file created by the `run()` method.
            '-i', str(output_path),
            # Filter Option: Applies a complex filtergraph. The value `filter_complex_str` contains the string we built earlier 
            # (e.g., "[0:a]amerge=inputs=4[a_merged];[a_merged]pan=mono|c0=0.125*c0+...+0.125*c7[a_out]") to merge and downmix the audio streams.
            '-filter_complex', filter_complex_str,
            # Map Option: Selects which video stream to include in the output. `0:v:0` means the first (0) video stream (`v`) from 
            # the first input file (`0`).
            '-map', '0:v:0',
             # Map Option: Selects which audio stream to include in the output. `[a_out]` refers to the output label we defined at 
             # the end of our `filter_complex` string, which contains the final merged and panned mono audio.
            '-map', '[a_out]',
            # Codec Option: Sets the video codec (`c:v`) to `copy`. This tells FFmpeg *not* to re-encode the video, but just to 
            # copy the existing video data directly from the input to the output, which is much faster.
            '-c:v', 'copy',
            # Codec Option: Sets the audio codec (`c:a`) for the output audio stream. The `audio_codec` variable holds either `'aac'` or 
            # `'libopus'` depending on the original video codec.
            '-c:a', audio_codec,
             # Option: Disables data stream recording. This prevents FFmpeg from trying to copy potentially incompatible data streams. Had issues 
             # with timecode track `tmcd` and this fixed it
            '-dn',
            # Option: Finishes encoding when the shortest input stream ends. 
            '-shortest',
            # Option: Sets how much information FFmpeg prints to the console (stderr)
            '-loglevel', loglevel,
            # Option: Tells FFmpeg to print periodic progress statistics during the process.
            '-stats',
            # Global Option: Automatically overwrites the output file (`temp_output_filename`) if it already exists, without asking 
            # for confirmation.
            '-y',
        ]

        # Conditionally add the audio bitrate argument if it's not None
        if audio_bitrate_param:
            cmd.extend(['-b:a', audio_bitrate_param])
        # Add the final output filename
        cmd.append(temp_output_filename)

        # Log the command that will be executed (for debugging)
        logging.debug(f"Downmix Command: {' '.join(cmd)}")
        
        # Execute the command using subprocess.run
        subprocess.run(cmd, capture_output=True, text=True, check=True, encoding='utf-8')

        # Replace the original file with the new temporary file
        output_path.unlink()
        shutil.move(temp_output_filename, self.output_filename)

        self.message = (
                f"Encoding and mono downmix successful.) "
                f"is located at {output_path.resolve()}"
        )
        print("--- Mono Audio Downmix Completed ---")
        return True


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