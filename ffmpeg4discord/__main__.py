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
- main: The main function that parses command-line arguments and starts the encoding process or web server.
"""

import threading
import time
import webbrowser
from glob import glob
from pathlib import Path
from textwrap import dedent

from flask import Flask, render_template, request, url_for

from ffmpeg4discord import arguments
from ffmpeg4discord.twopass import TwoPass, seconds_to_timestamp
from ffmpeg4discord.versioning import check_for_update


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
        twopass.target_filesize -= 0.2

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
    webbrowser.open(f"http://localhost:{port}")


def cleanup_files(pattern: str) -> None:
    """
    Removes temporary files matching a given pattern.

    Args:
        pattern (str): The glob pattern to match files for cleanup.
    """
    for file in glob(pattern):
        Path(file).unlink()


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

    if web:
        port = args.pop("port")

    path = Path(args["filename"]).resolve()
    args["filename"] = path

    # instantiate the TwoPass class
    twopass = TwoPass(**args)

    if web:
        app = Flask(__name__, static_folder=path.parent)

        @app.route("/")
        def index():
            return render_template(
                "web.html",
                file_url=url_for("static", filename=path.name),
                twopass=twopass,
                version_info=version_info,
                alert_hidden=True,
                approx=approx,
            )

        @app.route("/encode", methods=["POST"])
        def form_twopass():
            # generate new times from the selection
            ss = int(request.form.get("startTime"))
            to = int(request.form.get("endTime"))
            twopass.length = to - ss
            twopass.times = {"ss": seconds_to_timestamp(ss), "to": seconds_to_timestamp(to)}
            target_filesize = float(request.form.get("target_filesize"))

            # update TwoPass from web form
            twopass.resolution = request.form.get("resolution")
            twopass.target_filesize = target_filesize
            twopass.crop = request.form.get("crop")
            twopass.output = Path(request.form.get("output"))
            twopass.codec = request.form.get("codec")
            twopass.framerate = int(framerate) if (framerate := request.form.get("framerate")) else None
            twopass.audio_br = (
                float(audio_br) * 1000 if (audio_br := request.form.get("audio_br")) else twopass.audio_br
            )
            twopass.verbose = bool(request.form.getlist("verbose"))

            # include audio (unchecked => no_audio)
            twopass.no_audio = not bool(request.form.getlist("include_audio"))

            # audio mixing mode (only relevant when audio is included)
            amix_mode = request.form.get("amix_mode")
            if amix_mode == "mix_normalize":
                twopass.amix = True
                twopass.amix_normalize = True
            elif amix_mode == "mix":
                twopass.amix = True
                twopass.amix_normalize = False
            else:
                twopass.amix = False
                twopass.amix_normalize = False

            # audio stream selection (0-based audio-stream order)
            astreams = request.form.getlist("astreams")
            if astreams:
                twopass.astreams = [int(i) for i in astreams]
            else:
                twopass.astreams = None

            # to loop or not to loop
            approx = bool(request.form.getlist("approx"))

            twopass_loop(twopass=twopass, target_filesize=target_filesize, approx=approx)

            return render_template(
                "web.html",
                file_url=url_for("static", filename=path.name),
                twopass=twopass,
                version_info=version_info,
                approx=approx,
            )

        threading.Thread(target=open_browser, args=[port], name="Open Browser").start()
        app.run("0.0.0.0", port=port)
    else:
        twopass_loop(twopass=twopass, target_filesize=twopass.target_filesize, approx=approx)
        print(twopass.message)


if __name__ == "__main__":
    main()
