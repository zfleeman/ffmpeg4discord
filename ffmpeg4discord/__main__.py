"""
This module provides the main entry point for the ffmpeg4discord application.

It supports both command-line and web-based interfaces for performing two-pass
video encoding using FFmpeg. The script allows users to specify various encoding
parameters and target file sizes, and it will iteratively adjust the encoding
settings to meet the desired output file size.

Functions:
- twopass_loop: Executes the two-pass encoding process in a loop until the target file size is achieved.
- open_browser: Opens the default web browser to the specified port.
- format_commands: Lists the ffmpeg commands for an encode with a short explanation.
- success_message: The message shown when an encode finishes.
- source_facts: Facts about the input video that the web page checks the form against.
- form_values: The values the web UI's form shows.
- parse_encode_form: Checks the web UI's form and turns it into EncodeSettings.
- main: The main function that parses command-line arguments and starts the encoding process or web server.
"""

import logging
import math
import re
import threading
import time
import webbrowser
from dataclasses import replace
from pathlib import Path
from textwrap import dedent

from flask import Flask, render_template, request, send_file, url_for

from ffmpeg4discord import arguments
from ffmpeg4discord.twopass import EncodeResult, EncodeSettings, TwoPass, available_codecs
from ffmpeg4discord.versioning import check_for_update

# smallest fraction the target size is cut by on each retry
MIN_RETRY_STEP = 0.02

# the formats the web UI accepts, e.g. 1280x720 and 255x0x1410x1080
RESOLUTION_PATTERN = re.compile(r"\d+x\d+")
CROP_PATTERN = re.compile(r"\d+x\d+x\d+x\d+")


def twopass_loop(twopass: TwoPass, settings: EncodeSettings, approx: bool = False) -> EncodeResult:
    """
    Encodes with `settings`, then re-encodes at a lower bitrate until the output is under the target size.

    Args:
        twopass (TwoPass): The TwoPass for the input video.
        settings (EncodeSettings): What to encode. Its `target_filesize` is the size to get under.
        approx (bool): Keep the first encode, even if it's over the target.

    Returns:
        The last encode's result.
    """
    target_filesize = settings.target_filesize

    while True:
        result = twopass.run(settings)

        # check if the filesize is within the target
        if result.output_filesize < target_filesize or approx:
            break

        print(
            dedent(
                f"""\033[31m
                The output file size ({round(result.output_filesize, 2)}MB) is still above the target of {target_filesize}MB.
                Restarting...
                \033[0m"""
            )
        )
        Path(result.output_filename).unlink()

        # lower the target size for the next run, which lowers the bitrate.
        # scale by how far off we are, but always cut by at least MIN_RETRY_STEP so an output
        # that lands just over the target doesn't retry at a near-identical bitrate
        adjustment_ratio = min(target_filesize / result.output_filesize, 1 - MIN_RETRY_STEP)
        settings = replace(settings, target_filesize=max(settings.target_filesize * adjustment_ratio, 0.1))

    return result


def open_browser(port: int) -> None:
    """
    Opens the default web browser to the specified port.

    Args:
        port (int): The port number to open in the web browser.
    """
    time.sleep(0.5)
    webbrowser.open(f"http://127.0.0.1:{port}")


def format_commands(commands: list[str]) -> str:
    """
    Lists the ffmpeg commands for an encode, so users can see what ff4d did on their behalf.

    Args:
        commands (list[str]): The commands from `EncodeResult.commands`.
    """
    if len(commands) == 1:
        header = "Here's what this encode looks like as a plain FFmpeg command:"
    else:
        header = "Here's what this encode looks like as plain FFmpeg commands (a two-pass encode runs FFmpeg twice):"
    return "\n\n".join([header, *commands])


def success_message(result: EncodeResult) -> str:
    """The message shown when an encode finishes."""
    output_path = Path(result.output_filename).resolve()
    return f"Your compressed video file ({round(result.output_filesize, 2)}MB) is located at {output_path}"


def source_facts(twopass: TwoPass) -> dict:
    """Facts about the input video that the web page's JavaScript checks the form against."""
    stream = twopass.video_stream or {}
    width, height = stream.get("width"), stream.get("height")
    # Phones often store video sideways with a rotation tag, and ffmpeg's filters see the rotated size.
    rotation = int(stream.get("tags", {}).get("rotate", 0))
    for data in stream.get("side_data_list", []):
        rotation = int(data.get("rotation", rotation))
    if rotation % 180 == 90:
        width, height = height, width

    return {
        "duration": twopass.duration,
        "width": width,
        "height": height,
        "framerate": twopass.init_framerate,
        "size_mib": twopass.input_filesize,
        "audio_tracks": len(twopass.audio_streams),
        "audio_kbps": twopass.source_audio_br / 1000 if twopass.source_audio_br else None,
    }


def form_values(twopass: TwoPass, settings: EncodeSettings, approx: bool, form=None) -> dict:
    """
    The values the web UI's form shows. They come from `settings`, or from `form` when the page is shown again
    after a bad submit, so the user keeps what they typed.

    Args:
        twopass (TwoPass): The TwoPass for the input video.
        settings (EncodeSettings): The settings that fill the form.
        approx (bool): Whether the "Approximate file size" switch is on.
        form: The submitted form (Flask's `request.form`), if any.
    """
    if settings.amix:
        amix_mode = "mix_normalize" if settings.amix_normalize else "mix"
    else:
        amix_mode = "off"

    start, end = twopass.clip_times(settings)
    source_kbps = twopass.source_audio_br / 1000 if twopass.source_audio_br else ""
    values = {
        "startTime": start,
        "endTime": end,
        "target_filesize": settings.target_filesize,
        "approx": approx,
        "resolution": settings.resolution,
        "crop": settings.crop,
        "output": settings.output.resolve(),
        "codec": settings.codec,
        "framerate": settings.framerate or "",
        "audio_br": settings.audio_br or source_kbps,
        "include_audio": not settings.no_audio,
        "amix_mode": amix_mode,
        "astreams": settings.astreams,  # None means every track is checked
        "verbose": settings.verbose,
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


def parse_encode_form(form, twopass: TwoPass, codecs: list[str]) -> tuple[EncodeSettings | None, list[str]]:
    """
    Checks the web UI's form and turns it into EncodeSettings.

    Args:
        form: The submitted form (Flask's `request.form`).
        twopass (TwoPass): The TwoPass for the input video, used for its duration, size, and audio tracks.
        codecs (list[str]): The codecs this computer can use.

    Returns:
        The settings and an empty list, or None and a list of error messages for the user.
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
    if target is None or target <= 0:
        errors.append("The File Size must be a number above 0.")
    elif target > twopass.input_filesize:
        errors.append(
            f"The File Size ({target:g} MiB) is larger than the input file ({twopass.input_filesize:.2f} MiB)."
        )

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

    if errors:
        return None, errors

    amix_mode = form.get("amix_mode")
    settings = EncodeSettings(
        target_filesize=target,
        output=output,
        start=str(start),
        end=str(end),
        audio_br=audio_kbps,  # None (left blank) means the input's audio bitrate
        codec=codec,
        crop=crop,
        resolution=resolution,
        framerate=framerate,
        no_audio=not include_audio,
        amix=amix_mode in ("mix", "mix_normalize"),
        amix_normalize=amix_mode == "mix_normalize",
        astreams=astreams or None,
        verbose="verbose" in form,
    )
    return settings, []


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

    path = Path(args.pop("filename")).resolve()
    args["output"] = Path(args["output"])
    # the rest of the args are the encode settings
    settings = EncodeSettings(**args)
    twopass = TwoPass(path)

    if web:
        # --from and --to fill in the form's starting trim, so check them before starting the server
        twopass.clip_times(settings)
        codecs = available_codecs()
        source = source_facts(twopass)
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
                source=source,
                codecs=codecs,
                version_info=version_info,
                values=values,
                **kwargs,
            )

        @app.route("/")
        def index():
            return render_page(form_values(twopass, settings, approx), alert_hidden=True)

        @app.route("/encode", methods=["POST"])
        def form_twopass():
            # Each request builds its own settings, so nothing carries over from the last encode.
            form_settings, errors = parse_encode_form(request.form, twopass, codecs)
            # to loop or not to loop
            approx = "approx" in request.form

            if not errors:
                try:
                    result = twopass_loop(twopass, form_settings, approx)
                except ValueError as exc:
                    # TwoPass raises ValueError for settings that can't work, e.g. no bitrate left for video
                    errors = [str(exc)]
                except RuntimeError as exc:
                    # FFmpeg failed. Its own message and the full command are only useful in the terminal.
                    logging.error(exc)
                    errors = ["FFmpeg failed while encoding. Its error message is in the terminal running ff4d."]

            if errors:
                values = form_values(twopass, settings, approx, request.form)
                return render_page(values, alert_hidden=True, errors=errors), 400

            return render_page(
                form_values(twopass, form_settings, approx),
                message=success_message(result),
                commands_text=format_commands(result.commands),
            )

        threading.Thread(target=open_browser, args=[port], name="Open Browser").start()
        # Only this computer can reach the server. The form can write files anywhere, so keep it off the network.
        app.run("127.0.0.1", port=port)
    elif dry_run:
        result = twopass.run(settings, dry_run=True)
        print(format_commands(result.commands))
        if not approx:
            print("\nIf the output lands over the target size, ff4d re-encodes it at a lower bitrate.")
    else:
        result = twopass_loop(twopass, settings, approx)
        print(f"\n{format_commands(result.commands)}\n")
        print(success_message(result))


if __name__ == "__main__":
    main()
