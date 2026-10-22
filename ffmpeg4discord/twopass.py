"""
This module provides the TwoPass class and utility functions for performing two-pass video encoding using FFmpeg.

The TwoPass class allows users to compress video files to a specified target file size while maintaining
optimal video quality. It supports various encoding parameters such as codec, resolution, and audio bitrate.
The module also includes helper functions for timestamp conversion.

Classes:
- EncodeSettings: What the user asked for, like the target size, trim times, and codec.
- EncodeResult: The output file, its size, and the ffmpeg commands from one encode.
- TwoPass: Encodes and resizes video files using FFmpeg's two-pass encoding to meet a specified target file size.

Functions:
- available_codecs: Returns the codec choices for this operating system.
- command_for_display: Turns one encoding pass into a command the user can paste into a terminal.
- ffmpeg_major_version: Returns the installed ffmpeg's major version from the probe data.
- fps_mode_flag: Returns the frame rate flag name supported by the installed ffmpeg.
- run_pass: Runs one encoding pass and reports ffmpeg failures with a readable message.
- seconds_from_ts_string: Converts a timestamp string into seconds.
- seconds_to_timestamp: Converts seconds into a timestamp string.
- timestamp_from_percentage: Converts a percentage of the video's duration into a timestamp string.
- tonemap_filters: Returns the HDR-to-SDR filter chain this system's ffmpeg can run.
"""

import logging
import math
import os
import re
import shlex
import string
import sys
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from textwrap import dedent
from typing import Callable, Optional

import ffmpeg

logging.getLogger().setLevel(logging.INFO)


# Note: FILE_SIZE_MULT converts bytes to mebibytes (MiB, 1 MiB = 1,048,576 bytes).
# macOS Finder reports file sizes in megabytes (MB, 1 MB = 1,000,000 bytes),
# while Windows File Explorer reports in mebibytes (but labels as MB).
# This can cause discrepancies in reported file sizes between the two systems.
FILE_SIZE_MULT = 0.00000095367432


# ff4d codec names mapped to ffmpeg encoder names, ordered from most to least compatible.
CODEC_ENCODERS = {
    "x264": "libx264",
    "h264_nvenc": "h264_nvenc",
    "h264_videotoolbox": "h264_videotoolbox",
    "x265": "libx265",
    "hevc_nvenc": "hevc_nvenc",
    "hevc_videotoolbox": "hevc_videotoolbox",
    "vp9": "libvpx-vp9",
    "av1": "libaom-av1",
}

# Hardware encoders ignore ffmpeg's two-pass stats file, so ff4d encodes them in a single pass.
HARDWARE_CODECS = {"h264_nvenc", "hevc_nvenc", "h264_videotoolbox", "hevc_videotoolbox"}

# Characters that cmd and PowerShell both leave alone, so an argument made only of these needs no quotes.
WINDOWS_SAFE_CHARS = set(string.ascii_letters + string.digits + "-_./\\:=+")

# ffprobe `color_transfer` values that mean the video is HDR: PQ (HDR10, Dolby Vision) and HLG.
HDR_TRANSFERS = {"smpte2084", "arib-std-b67"}


def available_codecs() -> list[str]:
    """Return the codecs from `CODEC_ENCODERS` that this operating system can use.

    VideoToolbox only exists on macOS, so it is hidden elsewhere. NVENC is always listed because we
    can't cheaply tell whether an NVIDIA GPU is present; `run_pass` explains that failure if it happens.
    """

    return [c for c in CODEC_ENCODERS if "videotoolbox" not in c or sys.platform == "darwin"]


def ffmpeg_major_version(probe: dict) -> Optional[int]:
    """Return ffmpeg's major version from the `-show_program_version` section of the probe.

    That reports ffprobe's version, but ffmpeg and ffprobe ship together in every packaging we
    support, so they agree in practice. Version strings vary by build ("9.0.1", "n7.1",
    "4.4.2-0ubuntu0.22.04.1"), so we only take the leading number. Returns None when it can't be
    read, which happens with git/nightly builds ("N-119043-g1234567"). Those are always recent.
    """

    version = probe.get("program_version", {}).get("version", "")

    try:
        return int(version.split(".")[0].lstrip("nN"))
    except ValueError:
        return None


def fps_mode_flag(probe: dict) -> str:
    """Return the frame rate flag name this system's ffmpeg understands.

    ffmpeg 5.0 replaced `-vsync` with `-fps_mode`, and 9.0 removed `-vsync` entirely. We assume the
    modern flag when the version can't be read, because those are newer nightly builds.
    """

    major = ffmpeg_major_version(probe)
    return "fps_mode" if major is None or major >= 5 else "vsync"


def tonemap_filters(probe: dict) -> Optional[list[tuple[str, dict]]]:
    """Return the filters that convert HDR video to SDR, as (filter name, options) pairs.

    Both chains convert the picture to linear light, squeeze the bright HDR highlights into SDR's
    range with the `mobius` curve, then convert back to standard BT.709 video. `mobius` keeps game
    footage about as bright as the source, where `hable` came out noticeably darker. They differ in
    which filter does the color math:

    - `zscale` is the usual choice, but it only exists when ffmpeg was built with libzimg. The
      probe's `configuration` string lists the build flags, so checking it costs nothing.
    - ffmpeg 8.0 taught the built-in `scale` filter the same color conversions, so it works as a
      fallback on builds without `zscale` (like Homebrew's). It treats 203 nits as SDR white, so
      the `zscale` chain sets `npl=203` to make both chains look the same.

    Returns None when neither is available.
    """

    configuration = probe.get("program_version", {}).get("configuration", "")
    tonemap = ("tonemap", {"tonemap": "mobius", "desat": 0})

    if "--enable-libzimg" in configuration:
        return [
            ("zscale", {"t": "linear", "npl": 203}),
            ("format", {"pix_fmts": "gbrpf32le"}),
            ("zscale", {"p": "bt709"}),
            tonemap,
            ("zscale", {"t": "bt709", "m": "bt709", "r": "tv"}),
        ]

    major = ffmpeg_major_version(probe)
    if major is None or major >= 8:
        return [
            ("scale", {"out_transfer": "linear", "out_primaries": "bt709"}),
            ("format", {"pix_fmts": "gbrpf32le"}),
            tonemap,
            (
                "scale",
                {
                    "in_transfer": "linear",
                    "in_primaries": "bt709",
                    "out_transfer": "bt709",
                    "out_primaries": "bt709",
                    "out_color_matrix": "bt709",
                    "out_range": "tv",
                },
            ),
        ]

    return None


def command_for_display(ffoutput) -> str:
    """Turn one encoding pass into a command the user can paste into their terminal.

    Pass 1 sends its output to `pipe:` and throws it away, so we show the null device a person would type instead.
    """
    # compile() can contain Path objects, so stringify each argument.
    args = [str(arg) for arg in ffoutput.compile()]
    if args[-1] == "pipe:":
        args[-1] = "NUL" if sys.platform == "win32" else "/dev/null"

    if sys.platform != "win32":
        return shlex.join(args)

    # shlex quotes with single quotes, which cmd doesn't understand. Double quotes work in cmd and PowerShell.
    return " ".join(
        arg if arg and set(arg) <= WINDOWS_SAFE_CHARS else '"' + arg.replace('"', '\\"') + '"' for arg in args
    )


def run_pass(ffoutput, pass_name: str, hint: str = "", **run_kwargs):
    """Run a single encoding pass, replacing ffmpeg-python's detail-free exception with a useful one.

    ffmpeg-python raises `Error("ffmpeg error (see stderr output for detail)")`, which tells the user
    nothing. ffmpeg has already printed the real reason to the terminal, so we say where to look and
    include the command we ran. `hint` adds a suggestion to the message, e.g. for hardware encoders.
    """

    try:
        return ffoutput.run(**run_kwargs)
    except ffmpeg.Error as exc:
        # compile() can contain Path objects, so stringify each argument before joining.
        command = " ".join(str(arg) for arg in ffoutput.compile())
        raise RuntimeError(
            "\033[31m"
            + dedent(
                f"""
                FFmpeg failed during the {pass_name} pass.

                Look for FFmpeg's error message printed above this traceback -- it names the actual
                problem (an unsupported option, a bad filter, a missing encoder, etc.).

                The command that failed was:
                {command}
                """
            ).strip()
            + (f"\n\n{hint}" if hint else "")
            + "\033[0m"
        ) from exc


# Per-codec tweaks for `_generate_params()`.
# Kept module-level (instead of inside the method) so tests can patch it and
# exercise the `overrides.get("both", {})` branch.
CODEC_OVERRIDES = {
    "x264": {"pass2": {"c:a": "aac"}},
    "x265": {"pass2": {"tag:v": "hvc1", "c:a": "aac"}},
    "h264_nvenc": {"pass2": {"c:a": "aac"}},
    "hevc_nvenc": {"pass2": {"tag:v": "hvc1", "c:a": "aac"}},
    "h264_videotoolbox": {"pass2": {"c:a": "aac"}},
    "hevc_videotoolbox": {"pass2": {"tag:v": "hvc1", "c:a": "aac"}},
    "vp9": {
        "pass2": {"c:a": "libopus", "row-mt": 1, "cpu-used": 5, "deadline": "good"},
    },
    "av1": {
        "pass2": {"tag:v": "av01", "c:a": "libopus", "row-mt": 1, "cpu-used": 8},
    },
}


@dataclass
class EncodeSettings:
    """
    What the user asked for. The CLI builds one from its flags and the web UI builds one from its form.

    Attributes:
        target_filesize (float): Desired output size in MiB.
        output (Path): The output file, or a folder to save a generated file name in.
        start (str): Where the clip starts: a timestamp, seconds, or a percentage, e.g. "00:00:10.5", "90", or "75%".
        end (str): Where the clip stops, in the same formats. None means the end of the video.
        filename_times (bool): Read the start and end from the file name instead, e.g. "000010-000030.mp4".
        audio_br (float): Audio bitrate in kbps. None means the input's audio bitrate.
        codec (str): A key of `CODEC_ENCODERS`, e.g. "x264".
        crop (str): x offset, y offset, width, and height joined by x, e.g. "255x0x1410x1080".
        resolution (str): Output width and height, e.g. "1280x720".
        framerate (int): Output frames per second. None keeps the input's frame rate.
        no_audio (bool): Leave audio out of the output.
        amix (bool): Mix the selected audio tracks into one.
        amix_normalize (bool): Even out the volume while mixing.
        astreams (list[int]): The 0-based audio tracks to use. None means all of them.
        verbose (bool): Show ffmpeg's detailed logging.
    """

    target_filesize: float
    output: Path = Path()
    start: Optional[str] = None
    end: Optional[str] = None
    filename_times: bool = False
    audio_br: Optional[float] = None
    codec: str = "x264"
    crop: str = ""
    resolution: str = ""
    framerate: Optional[int] = None
    no_audio: bool = False
    amix: bool = False
    amix_normalize: bool = False
    astreams: Optional[list[int]] = None
    verbose: bool = False


@dataclass
class EncodeResult:
    """What one call to `TwoPass.run()` produced."""

    output_filename: str
    output_filesize: float  # in MiB, or 0 for a dry run
    commands: list[str]  # the ffmpeg commands, for showing to the user


class TwoPass:
    """
    Encodes a video to a target file size with ffmpeg's two-pass encoding.

    A TwoPass reads the input with ffprobe once and keeps what it learns, like the duration and audio tracks.
    Each call to `run()` takes the `EncodeSettings` to encode with, so one TwoPass can run many encodes.

    Two-Pass encoding documentation: https://trac.ffmpeg.org/wiki/Encode/H.264#twopass

    Attributes:
        filename (Path): The input video.
        probe (dict): ffprobe's output for the input.
        duration (float): The input's length in seconds.
        input_filesize (float): The input's size in MiB.
        width (int): The input's width as ffmpeg's filters see it, after any rotation. None without video.
        height (int): The input's height, the same way.
        ratio (float): The input's width divided by its height.
        init_framerate (int): The input's frames per second, rounded.
        audio_streams (list[dict]): The probe's audio streams, in order.
        source_audio_br (float): The first audio track's bitrate in bits per second, or None without audio.
        video_stream (dict): The probe's video stream.
        tonemap (list): The HDR-to-SDR filters for an HDR input, or None.
    """

    def __init__(self, filename: Path) -> None:
        self.filename = filename
        self.width = None
        self.height = None
        self.ratio = None
        self.init_framerate = None
        self.audio_streams = []
        self.video_stream = None
        self.tonemap = None

        # `show_program_version` adds the ffmpeg version to the probe output, which fps_mode_flag() needs.
        self.probe = ffmpeg.probe(filename=filename, show_program_version=None)
        self._process_probe()

    def _parse_streams(self):
        """Helper to parse video and audio streams from the probe output.

        Returns:
            The ffprobe "index" of the *first audio stream* (if any). This is only used for audio bitrate lookup.
        """

        audio_stream = None
        for stream in self.probe["streams"]:
            codec_type = stream["codec_type"]
            if codec_type == "video":
                self.video_stream = stream
                self.width, self.height = stream["width"], stream["height"]
                # Phones often store video sideways with a rotation tag, and ffmpeg's filters see the rotated size.
                rotation = int(stream.get("tags", {}).get("rotate", 0))
                for data in stream.get("side_data_list", []):
                    rotation = int(data.get("rotation", rotation))
                if rotation % 180 == 90:
                    self.width, self.height = self.height, self.width
                self.ratio = self.width / self.height
                framerate_ratio: str = stream.get("r_frame_rate")
                self.init_framerate = round(int(framerate_ratio.split("/")[0]) / int(framerate_ratio.split("/")[1]))
            elif codec_type == "audio":
                audio_stream = stream["index"]
                self.audio_streams.append(stream)

        return audio_stream

    def _process_probe(self):
        """
        Processes the ffmpeg probe output to set the duration, size, ratio, framerate, and audio bitrate attributes.
        """
        self.duration = float(self.probe["format"]["duration"])
        # in mebibytes (MiB, 1 MiB = 1,048,576 bytes), like the target size
        self.input_filesize = float(self.probe["format"]["size"]) * FILE_SIZE_MULT

        audio_stream = self._parse_streams()

        self.source_audio_br = None
        if audio_stream is not None:
            self.source_audio_br = float(self.probe["streams"][audio_stream]["bit_rate"])
        else:
            logging.warning("No audio stream found in the media file.")

        self._check_hdr()

    def _check_hdr(self):
        """Pick a tone-mapping filter chain when the source is HDR, or warn if ffmpeg can't do it."""

        if not self.video_stream or self.video_stream.get("color_transfer") not in HDR_TRANSFERS:
            return

        self.tonemap = tonemap_filters(self.probe)
        if not self.tonemap:
            logging.warning(
                "\033[31m"
                + dedent(
                    """
                    This video is HDR, but your ffmpeg can't convert it to SDR. It needs ffmpeg 8.0
                    or newer, or a build with zscale (libzimg). The output may look washed out.
                    """
                ).strip()
                + "\033[0m"
            )

    def clip_times(self, settings: EncodeSettings) -> tuple[float, float]:
        """
        Returns where the clip starts and ends, in seconds.

        The times come from the file name when `settings.filename_times` is set, otherwise from `settings.start`
        and `settings.end`. Without either, the clip is the whole video.
        """
        if settings.filename_times:
            start, end = self._times_from_file_name()
        else:
            # Accept any supported format (timestamp, seconds, or percentage).
            start = seconds_from_ts_string(timestamp_from_percentage(settings.start or "0", self.duration))
            end = self.duration
            if settings.end:
                end = seconds_from_ts_string(timestamp_from_percentage(settings.end, self.duration))

        if end <= start:
            raise ValueError(
                "\033[31m"
                + dedent(
                    f"""
                    Time Paradox?

                    Something is wrong with your clipping times. Use this
                    information to further diagnose the problem:

                    - Your video is {seconds_to_timestamp(self.duration)} long
                    - Your clipping times are {seconds_to_timestamp(start)} to {seconds_to_timestamp(end)}
                    """
                ).strip()
                + "\033[0m"
            )

        return start, end

    def _times_from_file_name(self) -> tuple[float, float]:
        """
        Reads the start and optional end time from a file name like "HHMMSS.mp4" or "HHMMSS-HHMMSS.mp4".

        Without an end time, the clip runs to the end of the video. A name in neither format gets the whole video.
        """
        fname = self.filename.name

        try:
            start = seconds_from_ts_string(f"{fname[0:2]}:{fname[2:4]}:{fname[4:6]}")
        except ValueError:
            logging.warning("Warning: Invalid time format in filename. Defaulting to full duration.")
            return 0.0, self.duration

        # Check if there is an additional six digits for end time
        if len(fname) > 6 and fname[7:13].isdigit():
            return start, seconds_from_ts_string(f"{fname[7:9]}:{fname[9:11]}:{fname[11:13]}")

        return start, self.duration

    def _audio_bitrate(self, settings: EncodeSettings) -> Optional[float]:
        """The audio bitrate to encode with, in bits per second."""
        return settings.audio_br * 1000 if settings.audio_br else self.source_audio_br

    def _generate_params(self, settings: EncodeSettings, bitrate_targets: dict) -> dict:
        """
        Create params for the ffmpeg.output() function
        :param settings: the encode's settings
        :param bitrate_targets: the video bitrate flags from `_bitrate_targets()`
        :return: dictionary containing parameters for ffmpeg's first and second pass.
        """

        codec = settings.codec
        params = {
            "pass1": {
                "pass": 1,
                "f": "null",
                fps_mode_flag(self.probe): "cfr",  # force CFR; flag name varies by ffmpeg version
                "c:v": CODEC_ENCODERS.get(codec, codec),
                "pix_fmt": "yuv420p",
            },
            "pass2": {
                "pass": 2,
                "b:a": self._audio_bitrate(settings),
                "c:v": CODEC_ENCODERS.get(codec, codec),
                # 8-bit 4:2:0 is the only format browsers, phones, and Discord's player reliably decode
                "pix_fmt": "yuv420p",
                "ac": 2,  # downmix to stereo b/c current audio compression technique doesn't like 5.1 channel tracks
                "map_chapters": -1,  # remove chapters from output files, as it messes up total video length
            },
        }

        # Tone-mapped video is SDR now. Without these, ffmpeg copies the source's HDR labels.
        if self.tonemap:
            params["pass2"].update({"color_primaries": "bt709", "color_trc": "bt709", "colorspace": "bt709"})

        # assign the output framerate
        if settings.framerate:
            if settings.framerate < self.init_framerate:
                params["pass1"]["r"] = settings.framerate
                params["pass2"]["r"] = settings.framerate
            else:
                logging.warning(
                    "\033[31m"
                    + dedent(
                        f"""
                        Desired framerate ({settings.framerate}) is more than original framerate ({self.init_framerate}).
                        Keeping the original framerate...
                        """
                    ).strip()
                    + "\033[0m"
                )

        # add in configurations specific to the codec
        if codec == "x265":
            # two pass is different for x265
            _ = params["pass1"].pop("pass")
            _ = params["pass2"].pop("pass")
            params["pass1"]["x265-params"] = "pass=1"
            params["pass2"]["x265-params"] = "pass=2"
        elif codec in HARDWARE_CODECS:
            # single pass: without -pass 2, ffmpeg won't look for a stats file that was never written
            _ = params["pass1"].pop("pass")
            _ = params["pass2"].pop("pass")

        overrides = CODEC_OVERRIDES.get(codec)
        if overrides:
            # Apply shared params to both passes
            for key, value in overrides.get("both", {}).items():
                params["pass1"][key] = value
                params["pass2"][key] = value

            # Apply pass-specific params
            params["pass1"].update(overrides.get("pass1", {}))
            params["pass2"].update(overrides.get("pass2", {}))

        # Apply bitrate targets to both passes
        for pass_params in params.values():
            pass_params.update(**bitrate_targets)

        return params

    @staticmethod
    def _with_pass_log(pass_params: dict, codec: str, log_dir: str) -> dict:
        """A copy of one pass's params that writes the two-pass stats to `log_dir` instead of the working directory."""
        if codec in HARDWARE_CODECS:
            return pass_params  # single pass, so there are no stats
        if codec == "x265":
            # x265 ignores -passlogfile. ffmpeg splits x265-params on ":" and treats ' and \ as quoting,
            # so those need a backslash in front, e.g. the colon in a Windows drive letter.
            stats = re.sub(r"([\\':])", r"\\\1", Path(log_dir, "x265_2pass.log").as_posix())
            return {**pass_params, "x265-params": f"{pass_params['x265-params']}:stats={stats}"}
        return {**pass_params, "passlogfile": str(Path(log_dir, "ffmpeg2pass"))}

    def _bitrate_targets(self, settings: EncodeSettings, length: float) -> dict:
        """Compute the video bitrate flags that fit `settings.target_filesize` into a `length`-second clip."""

        # No audio track is written with --no-audio or without an audio stream, so neither takes any of the budget.
        audio_bps = self._audio_bitrate(settings)
        audio_kbps = 0 if settings.no_audio or not self.audio_streams or not audio_bps else audio_bps / 1000
        br = math.floor((settings.target_filesize * 8192) / length - audio_kbps) * 1000

        # Long clips with small targets can leave nothing for video after audio is subtracted.
        if br <= 0:
            raise ValueError(
                f"Target file size of {settings.target_filesize:.2f} MiB is too small for a {length:g}-second clip "
                f"with {audio_kbps:g} kbps audio: there is no bitrate left for video. "
                "Try a larger target size (File Size, or -s), a shorter clip, a lower audio bitrate "
                "(Audio Bitrate, or -a), or no audio (turn off Include Audio, or -an)."
            )

        return {
            "b:v": br,
            "minrate": br * 0.5,
            "maxrate": br * 1.45,
            "bufsize": br * 2,
        }

    def _check_video_size(self, settings: EncodeSettings) -> None:
        """Raise a ValueError for a crop or resolution that ffmpeg would reject or quietly change."""

        if settings.crop:
            x, y, crop_width, crop_height = (int(n) for n in settings.crop.split("x"))
            # ffmpeg doesn't fail here. It quietly moves the crop inside the frame, which isn't what was asked for.
            if self.width and (x + crop_width > self.width or y + crop_height > self.height):
                raise ValueError(
                    f"The Crop (-x) {settings.crop} goes past the edge of the {self.width}x{self.height} video. "
                    f"Keep x offset + width at most {self.width} and y offset + height at most {self.height}."
                )

        # x264 and x265 only encode even sizes. The output size is the resolution, or the crop without one.
        if settings.codec not in ("x264", "x265"):
            return
        if settings.resolution:
            width, height = (int(n) for n in settings.resolution.split("x"))
            if width % 2 or height % 2:
                raise ValueError(
                    f"{settings.codec} needs an even width and height, but the Resolution (-r) is "
                    f"{settings.resolution}. Use even numbers, e.g. 1280x720."
                )
        elif settings.crop and (crop_width % 2 or crop_height % 2):
            raise ValueError(
                f"{settings.codec} needs an even width and height, but the Crop (-x) is {crop_width}x{crop_height}. "
                "Use an even crop width and height, or set an even Resolution (-r)."
            )

    def _check_audio_tracks(self, settings: EncodeSettings) -> None:
        """Raise a ValueError for an --astreams number that doesn't match an audio track in the file."""

        # --no-audio drops every track, so the numbers don't matter.
        if settings.no_audio or not settings.astreams:
            return
        count = len(self.audio_streams)
        for i in settings.astreams:
            if i >= count:
                if count == 0:
                    tracks = "This file has no audio tracks."
                elif count == 1:
                    tracks = "This file has 1 audio track, numbered 0."
                else:
                    tracks = f"This file has {count} audio tracks, numbered 0 to {count - 1}."
                raise ValueError(f"Audio track {i} doesn't exist. {tracks}")

    def _output_filename(self, settings: EncodeSettings) -> str:
        """
        Returns the file to write. A folder gets a generated name, and a file name's extension is fixed to match the codec.
        """
        ext = ".webm" if "vp9" in settings.codec else ".mp4"
        output = settings.output.resolve()

        if output.is_dir():
            name = "small_" + self.filename.stem.replace(" ", "_") + f"_{settings.codec}"
            return str(output / (name + datetime.strftime(datetime.now(), f"_%Y%m%d%H%M%S{ext}")))

        if output.suffix != ext:
            logging.warning(
                "\033[31m"
                + dedent(
                    f"""
                    You specified {settings.codec}, but your output file name ends with {output.suffix}.
                    I've corrected this.
                    """
                ).strip()
                + "\033[0m"
            )
            output = output.with_suffix(ext)

        return str(output)

    def _apply_video_filters(self, video, settings: EncodeSettings):
        """
        Function to apply the crop and resolution parameters to a video object
        :param video: the ffmpeg video object from the Class's input video file
        :param settings: the encode's settings
        :return: the video object after it has been cropped or resized
        """

        ratio = self.ratio
        if settings.crop:
            crop = settings.crop.split("x")
            video = video.crop(x=crop[0], y=crop[1], width=crop[2], height=crop[3])
            ratio = int(crop[2]) / int(crop[3])

        if settings.resolution:
            video = video.filter("scale", settings.resolution)
            x = int(settings.resolution.split("x")[0])
            y = int(settings.resolution.split("x")[1])
            outputratio = x / y

            if ratio != outputratio:
                logging.warning(
                    "\033[31m"
                    + dedent(
                        """
                        Your output resolution's aspect ratio does not match the
                        input resolution's or your cropped resolution's aspect ratio.
                        """
                    ).strip()
                    + "\033[0m"
                )

        # Tone map last, so a smaller --resolution means fewer pixels to process.
        for name, options in self.tonemap or []:
            video = video.filter(name, **options)

        return video

    def _apply_audio_filters(self, ffinput, settings: EncodeSettings):
        """Select and/or mix audio streams.

        Selection is controlled by `settings.astreams` (0-based *audio stream order*, not ffprobe index).
        - If `settings.astreams` is None: select all (historical behavior).
        - If `settings.astreams` is []: select none.
        - If `settings.amix` is True: merge the selected streams.
        - If `settings.amix` is False: pick the first selected stream.
        """

        if not self.audio_streams:
            return None

        if settings.astreams is None:
            selected_positions = list(range(len(self.audio_streams)))
        else:
            selected_positions = settings.astreams  # run() already checked that each one is a real track

        if not selected_positions:
            return None

        # The bitrate budget covers one audio track, so without mixing we keep only the first selected one.
        # (`ffinput.audio` would map every track and push the output over the target size.)
        if not settings.amix:
            return ffinput[f"a:{selected_positions[0]}"]

        to_merge = [ffinput[f"a:{i}"] for i in selected_positions]
        return ffmpeg.filter(
            to_merge,
            "amix",
            normalize=int(settings.amix_normalize),
            inputs=len(selected_positions),
        )

    def run(
        self, settings: EncodeSettings, dry_run: bool = False, on_pass: Optional[Callable[[str, Path], None]] = None
    ) -> EncodeResult:
        """
        Perform the CPU-intensive encoding job
        :param settings: what to encode and how
        :param dry_run: build the ffmpeg commands without running them
        :param on_pass: called with the pass name ("first", "second", or "single") and a file that ffmpeg writes
            its progress to, just before each pass starts. The web UI uses it for its progress bar.
        :return: the output file, its size, and the ffmpeg commands
        """

        # The file size comparison uses mebibytes (MiB, 1 MiB = 1,048,576 bytes).
        if settings.target_filesize > self.input_filesize:
            raise ValueError(
                f"Your target file size is larger than the input file.\n"
                f"Input file size (in MiB):\t{self.input_filesize:.2f} MiB\n"
                f"Target file size (in MiB):\t{settings.target_filesize:.2f} MiB\n"
                "Note: File size is calculated in MiB (1 MiB = 1,048,576 bytes). "
                "macOS Finder uses MB (1 MB = 1,000,000 bytes), which may differ."
            )

        start, end = self.clip_times(settings)
        self._check_video_size(settings)
        self._check_audio_tracks(settings)
        output_filename = self._output_filename(settings)
        params = self._generate_params(settings, self._bitrate_targets(settings, end - start))

        # separate streams from ffinput
        ffinput = ffmpeg.input(self.filename, ss=seconds_to_timestamp(start), to=seconds_to_timestamp(end))
        video = self._apply_video_filters(ffinput.video, settings)
        audio = self._apply_audio_filters(ffinput, settings)

        # Set our logging level. We use "error" rather than "quiet" so that ffmpeg's own failure
        # messages reach the user; "-stats" still prints the progress line either way.
        loglevel = "verbose" if settings.verbose else "error"

        hardware = settings.codec in HARDWARE_CODECS
        hint = (
            f"{settings.codec} is a hardware encoder and needs matching hardware and drivers. "
            "If yours doesn't have it, try a software codec like x264 (-c x264)."
            if hardware
            else ""
        )

        output_streams = [video, audio] if audio and not settings.no_audio else [video]

        def build_passes(pass1: dict, pass2: dict) -> tuple:
            """The first and second pass. The first is None for hardware encoders, which can't use its stats."""
            first = None if hardware else ffmpeg.output(video, "pipe:", **pass1)
            return first, ffmpeg.output(*output_streams, output_filename, **pass2)

        # The commands for the user leave out ff4d's logging flags and the temp stats folder, which is deleted after
        # the encode. Without that folder, ffmpeg keeps its stats in the working directory, so a copied command works.
        commands = [command_for_display(p) for p in build_passes(params["pass1"], params["pass2"]) if p is not None]
        if dry_run:
            return EncodeResult(output_filename, 0, commands)

        # A new folder for each encode, so two encodes at once can't read or delete each other's stats
        with tempfile.TemporaryDirectory(prefix="ff4d-", ignore_cleanup_errors=True) as log_dir:
            first_pass, second_pass = build_passes(
                self._with_pass_log(params["pass1"], settings.codec, log_dir),
                self._with_pass_log(params["pass2"], settings.codec, log_dir),
            )

            def with_logging(ffoutput, pass_name: str):
                """Adds ff4d's logging flags, plus a -progress file when `on_pass` is watching."""
                args = ["-loglevel", loglevel, "-stats"]
                if on_pass:
                    progress_file = Path(log_dir, f"{pass_name}-progress.txt")
                    args += ["-progress", str(progress_file)]
                    on_pass(pass_name, progress_file)
                return ffoutput.global_args(*args)

            if first_pass is not None:
                print("Performing first pass")
                run_pass(with_logging(first_pass, "first"), "first", capture_stdout=True)

            print("Performing single pass (hardware encoder)" if hardware else "\nPerforming second pass")
            pass_name = "single" if hardware else "second"
            run_pass(with_logging(second_pass, pass_name), pass_name, hint=hint, overwrite_output=True)

        return EncodeResult(output_filename, os.path.getsize(output_filename) * FILE_SIZE_MULT, commands)


def seconds_from_ts_string(ts_string: str) -> float:
    """
    Convert "HH:MM:SS", "MM:SS", or plain seconds, each with optional decimals like "01:30.250", into seconds.
    """
    parts = ts_string.strip().split(":")
    try:
        numbers = [float(part) for part in parts]
    except ValueError:
        numbers = []

    if not 1 <= len(numbers) <= 3 or any(n < 0 or not math.isfinite(n) for n in numbers):
        raise ValueError(f"Invalid time '{ts_string}'. Use HH:MM:SS, MM:SS, or seconds, e.g. 00:01:30.250 or 90.25.")

    seconds = 0.0
    for number in numbers:
        seconds = seconds * 60 + number
    return seconds


def timestamp_from_percentage(value: str, duration: float) -> str:
    """
    Convert a percentage like "75%" into a timestamp string for a video of `duration` seconds.
    Values without a "%" are returned unchanged.
    """
    if not value.endswith("%"):
        return value

    try:
        percent = float(value[:-1])
    except ValueError as e:
        raise ValueError(f"Invalid percentage '{value}'. Use a number followed by %, e.g. 75%.") from e

    if not 0 <= percent <= 100:
        raise ValueError(f"Invalid percentage '{value}'. It must be between 0% and 100%.")

    return seconds_to_timestamp(duration * percent / 100)


def seconds_to_timestamp(seconds: float) -> str:
    """
    Convert seconds into an "HH:MM:SS" string, adding ".mmm" when there are milliseconds.
    """
    # Work in whole milliseconds so float noise like 1.9999999 doesn't turn into "00:00:01.1000".
    ms = round(seconds * 1000)
    hours, ms = divmod(ms, 3_600_000)
    minutes, ms = divmod(ms, 60_000)
    secs, ms = divmod(ms, 1000)

    timestamp = f"{hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{timestamp}.{ms:03d}" if ms else timestamp
