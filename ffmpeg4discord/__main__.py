"""
This module provides the main entry point for the ffmpeg4discord application.

It supports both command-line and web-based interfaces for performing two-pass
video encoding using FFmpeg. The script allows users to specify various encoding
parameters and target file sizes, and it will iteratively adjust the encoding
settings to meet the desired output file size.

Functions:
- twopass_loop: Executes the two-pass encoding process in a loop until the target file size is achieved.
- open_browser: Opens the default web browser to the specified port.
- cleanup_files: Removes temporary files matching a given pattern.
- format_commands: Lists the ffmpeg commands for an encode with a short explanation.
- form_values: The values the web UI's form shows.
- parse_encode_form: Checks the web UI's form and turns it into TwoPass settings.
- main: The main function that parses command-line arguments and starts the encoding process or web server.
"""

import logging
import math
import re
import threading
import time
import webbrowser
from glob import glob
from pathlib import Path
from textwrap import dedent

from flask import Flask, render_template, request, send_file, url_for

from ffmpeg4discord import arguments
from ffmpeg4discord.twopass import FILE_SIZE_MULT, TwoPass, available_codecs, seconds_to_timestamp
from ffmpeg4discord.versioning import check_for_update

# smallest fraction the target size is cut by on each retry
MIN_RETRY_STEP = 0.02

# the formats the web UI accepts, e.g. 1280x720 and 255x0x1410x1080
RESOLUTION_PATTERN = re.compile(r"\d+x\d+")
CROP_PATTERN = re.compile(r"\d+x\d+x\d+x\d+")


def twopass_loop(twopass: TwoPass, target_filesize: float, approx: bool = False) -> None:
    """
    Executes the two-pass encoding process in a loop until the target file size is achieved.

    Args:
        twopass (TwoPass): An instance of the TwoPass class.
        target_filesize (float): The desired target file size in megabytes (MB).
        approx (bool): Whether to approximate the target file size without looping.
    """
    while True:
        # clean up before each run
        if twopass.codec == "x265":
            cleanup_files("x265_2pass*")
        else:
            cleanup_files("ffmpeg2pass*")

        # run the two-pass encoding
        current_filesize = twopass.run()
        output_fs = round(twopass.output_filesize, 2)

        # check if the filesize is within the target
        if current_filesize < target_filesize or approx:
            break

        print(
            dedent(
                f"""\033[31m
                The output file size ({output_fs}MB) is still above the target of {target_filesize}MB.
                Restarting...
                \033[0m"""
            )
        )
        Path(twopass.output_filename).unlink()

        # adjust the class's target file size to set a lower bitrate for the next run
        # scale by how far off we are, but always cut by at least MIN_RETRY_STEP so an output
        # that lands just over the target doesn't retry at a near-identical bitrate
        adjustment_ratio = min(target_filesize / current_filesize, 1 - MIN_RETRY_STEP)
        twopass.target_filesize = max(twopass.target_filesize * adjustment_ratio, 0.1)

    # set the final message
    output_path = Path(twopass.output_filename).resolve()
    twopass.message = f"Your compressed video file ({output_fs}MB) is located at {output_path}"

    # final cleanup
    if twopass.codec == "x265":
        cleanup_files("x265_2pass*")
    else:
        cleanup_files("ffmpeg2pass*")


def open_browser(port: int) -> None:
    """
    Opens the default web browser to the specified port.

    Args:
        port (int): The port number to open in the web browser.
    """
    time.sleep(0.5)
    webbrowser.open(f"http://127.0.0.1:{port}")


def cleanup_files(pattern: str) -> None:
    """
    Removes temporary files matching a given pattern.

    Args:
        pattern (str): The glob pattern to match files for cleanup.
    """
    for file in glob(pattern):
        Path(file).unlink()


def format_commands(commands: list[str]) -> str:
    """
    Lists the ffmpeg commands for an encode, so users can see what ff4d did on their behalf.

    Args:
        commands (list[str]): The commands saved by `TwoPass.run()`.
    """
    if len(commands) == 1:
        header = "Here's what this encode looks like as a plain FFmpeg command:"
    else:
        header = "Here's what this encode looks like as plain FFmpeg commands (a two-pass encode runs FFmpeg twice):"
    return "\n\n".join([header, *commands])


def form_values(twopass: TwoPass, approx: bool, form=None) -> dict:
    """
    The values the web UI's form shows. They come from `twopass`, or from `form` when the page is shown again
    after a bad submit, so the user keeps what they typed.

    Args:
        twopass (TwoPass): The TwoPass whose settings fill the form.
        approx (bool): Whether the "Approximate file size" switch is on.
        form: The submitted form (Flask's `request.form`), if any.
    """
    if twopass.amix:
        amix_mode = "mix_normalize" if twopass.amix_normalize else "mix"
    else:
        amix_mode = "off"

    values = {
        "startTime": twopass.from_seconds or 0,
        "endTime": twopass.to_seconds or twopass.duration,
        "target_filesize": twopass.target_filesize,
        "approx": approx,
        "resolution": twopass.resolution,
        "crop": twopass.crop,
        "output": twopass.output,
        "codec": twopass.codec,
        "framerate": twopass.framerate or "",
        "audio_br": twopass.audio_br / 1000 if twopass.audio_br else "",
        "include_audio": not twopass.no_audio,
        "amix_mode": amix_mode,
        "astreams": twopass.astreams,  # None means every track is checked
        "verbose": twopass.verbose,
    }
    if form is None:
        return values

    text_fields = [
        "startTime",
        "endTime",
        "target_filesize",
        "resolution",
        "crop",
        "output",
        "codec",
        "framerate",
        "audio_br",
    ]
    for name in text_fields:
        values[name] = form.get(name, "")
    for name in ["approx", "include_audio", "verbose"]:
        values[name] = name in form
    # The page disables the audio options when audio is off, so they're only in the form when it's on.
    if values["include_audio"]:
        values["amix_mode"] = form.get("amix_mode", "off")
        values["astreams"] = [int(i) for i in form.getlist("astreams") if i.isdecimal()]
    return values


def _number(text, convert=float):
    """Converts form text to a number. Returns None if it's blank, missing, or not a number."""
    try:
        value = convert(text.strip())
    except (AttributeError, ValueError):
        return None
    # float() accepts "nan" and "inf", which aren't useful settings
    return value if math.isfinite(value) else None


def parse_encode_form(form, twopass: TwoPass, codecs: list[str]) -> tuple[dict, list[str]]:
    """
    Checks the web UI's form and turns it into TwoPass settings.

    Args:
        form: The submitted form (Flask's `request.form`).
        twopass (TwoPass): The TwoPass for the input video, used for its duration, size, and audio tracks.
        codecs (list[str]): The codecs this computer can use.

    Returns:
        The settings, keyed by TwoPass attribute name, and a list of error messages for the user.
        Only use the settings when the list is empty.
    """
    errors = []

    start = _number(form.get("startTime"))
    end = _number(form.get("endTime"))
    if start is None or end is None:
        errors.append("The Start and End times must be numbers of seconds.")
    elif not 0 <= start < end <= twopass.duration:
        errors.append(
            f"The Start time must come before the End time, and both must be between 0 and {twopass.duration:g} seconds."
        )

    target = _number(form.get("target_filesize"))
    input_mib = float(twopass.probe["format"]["size"]) * FILE_SIZE_MULT
    if target is None or target <= 0:
        errors.append("The File Size must be a number above 0.")
    elif target > input_mib:
        errors.append(f"The File Size ({target:g} MiB) is larger than the input file ({input_mib:.2f} MiB).")

    codec = form.get("codec")
    if codec not in codecs:
        errors.append("Pick a Video Codec from the list.")

    resolution = form.get("resolution", "").strip()
    if resolution and not RESOLUTION_PATTERN.fullmatch(resolution):
        errors.append("The Resolution must be width x height, e.g. 1280x720, or left blank.")

    crop = form.get("crop", "").strip()
    if crop and not CROP_PATTERN.fullmatch(crop):
        errors.append(
            "The Crop must be four numbers joined by x (x offset, y offset, width, height), e.g. 255x0x1410x1080."
        )

    # Windows Explorer's "Copy as path" wraps the path in quotes
    output = Path(form.get("output", "").strip().strip('"'))
    if not output.is_dir() and not output.parent.is_dir():
        errors.append(f"The output folder {output.parent} doesn't exist.")

    # Frame rate and audio bitrate are optional, so only a filled-in field that isn't a valid number is an error.
    framerate = _number(form.get("framerate"), int)
    if form.get("framerate", "").strip() and (framerate is None or framerate <= 0):
        errors.append("The Frame Rate must be a whole number above 0, e.g. 30, or left blank to keep the original.")

    audio_kbps = _number(form.get("audio_br"))
    if form.get("audio_br", "").strip() and (audio_kbps is None or audio_kbps <= 0):
        errors.append("The Audio Bitrate must be a number above 0.")

    include_audio = "include_audio" in form
    astreams = [int(i) for i in form.getlist("astreams") if i.isdecimal()]
    # With more than one track the page shows a checkbox per track. Sending none would otherwise mean "all tracks".
    if include_audio and len(twopass.audio_streams) > 1 and not astreams:
        errors.append("Check at least one of the Audio Streams, or turn off Include Audio.")

    amix_mode = form.get("amix_mode")
    settings = {
        "from_seconds": start,
        "to_seconds": end,
        "target_filesize": target,
        "resolution": resolution,
        "crop": crop,
        "output": output,
        "codec": codec,
        "framerate": framerate,
        "audio_br": audio_kbps * 1000 if audio_kbps else twopass.audio_br,
        "verbose": "verbose" in form,
        "no_audio": not include_audio,
        "amix": amix_mode in ("mix", "mix_normalize"),
        "amix_normalize": amix_mode == "mix_normalize",
        "astreams": astreams or None,
    }
    return settings, errors


def main() -> None:
    """
    The main function that parses command-line arguments and starts the encoding process or web server.
    """
    # Best-effort version check (never blocks startup)
    version_info = check_for_update(timeout_s=1.5)

    # CLI: show version + update notice early (for both CLI mode and web-launch mode)
    if version_info.current_version:
        print(f"ffmpeg4discord v{version_info.current_version}")
    else:
        print("ffmpeg4discord")

    if version_info.update_available:
        print(
            dedent(
                f"""\033[33m
                Update available: {version_info.latest_version} (you are running {version_info.current_version}).
                Upgrade with: pip install -U ffmpeg4discord
                \033[0m"""
            ).strip()
        )

    # get args from the command line
    args = arguments.get_args()
    web = args.pop("web")
    approx = args.pop("approx")
    dry_run = args.pop("dry_run")

    if web and dry_run:
        logging.warning("--dry-run is ignored with --web. Pick your settings in the browser instead.")

    if web:
        port = args.pop("port")

    path = Path(args["filename"]).resolve()
    args["filename"] = path

    # instantiate the TwoPass class
    twopass = TwoPass(**args)

    if web:
        codecs = available_codecs()
        # No static folder: serving the video's folder would expose every file next to it.
        app = Flask(__name__, static_folder=None)

        @app.route("/video")
        def video():
            return send_file(path)

        def render_page(values: dict, **kwargs):
            return render_template(
                "web.html",
                file_url=url_for("video"),
                twopass=twopass,
                codecs=codecs,
                version_info=version_info,
                values=values,
                **kwargs,
            )

        @app.route("/")
        def index():
            return render_page(form_values(twopass, approx), alert_hidden=True)

        @app.route("/encode", methods=["POST"])
        def form_twopass():
            settings, errors = parse_encode_form(request.form, twopass, codecs)
            # to loop or not to loop
            approx = "approx" in request.form

            if not errors:
                for name, value in settings.items():
                    setattr(twopass, name, value)
                twopass.length = twopass.to_seconds - twopass.from_seconds
                twopass.times = {
                    "ss": seconds_to_timestamp(twopass.from_seconds),
                    "to": seconds_to_timestamp(twopass.to_seconds),
                }
                try:
                    twopass_loop(twopass=twopass, target_filesize=twopass.target_filesize, approx=approx)
                except ValueError as exc:
                    # TwoPass raises ValueError for settings that can't work, e.g. no bitrate left for video
                    errors = [str(exc)]
                except RuntimeError as exc:
                    # FFmpeg failed. Its own message and the full command are only useful in the terminal.
                    logging.error(exc)
                    errors = ["FFmpeg failed while encoding. Its error message is in the terminal running ff4d."]

            if errors:
                return render_page(form_values(twopass, approx, request.form), alert_hidden=True, errors=errors), 400

            return render_page(form_values(twopass, approx), commands_text=format_commands(twopass.commands))

        threading.Thread(target=open_browser, args=[port], name="Open Browser").start()
        # Only this computer can reach the server. The form can write files anywhere, so keep it off the network.
        app.run("127.0.0.1", port=port)
    elif dry_run:
        twopass.run(dry_run=True)
        print(format_commands(twopass.commands))
        if not approx:
            print("\nIf the output lands over the target size, ff4d re-encodes it at a lower bitrate.")
    else:
        twopass_loop(twopass=twopass, target_filesize=twopass.target_filesize, approx=approx)
        print(f"\n{format_commands(twopass.commands)}\n")
        print(twopass.message)


if __name__ == "__main__":
    main()
