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

    # final cleanup
    cleanup_files("ffmpeg2pass*")

    # set the final message
    output_path = Path(twopass.output_filename).resolve()
    twopass.message = f"Your compressed video file ({output_fs}MB) is located at {output_path}"


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
    # get args from the command line
    args = arguments.get_args()
    web = args.pop("web")
    approx = args.pop("approx")
    run_amerge = args.get("amerge", False)
    args.pop("amerge", None)

    if web:
        port = args.pop("port")

    path = Path(args["filename"]).resolve()
    
    # twopass needs these values now for downmixing
    args["filename"] = path
    args['amerge'] = run_amerge

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

            # to loop or not to loop
            approx = bool(request.form.getlist("approx"))

            # Get amerge state for this specific request
            web_amerge = "amerge_audio" in request.form
            # Set amerge flag on instance for this request
            twopass.amerge = web_amerge

            twopass_loop(twopass=twopass, target_filesize=target_filesize, approx=approx)

            # <<< Conditionally run downmix >>>
            # Check if loop likely succeeded and merge requested
            if twopass.output_filename and Path(twopass.output_filename).exists() and twopass.amerge:
                twopass.downmix_audio() # Call the method
            elif twopass.amerge and (not twopass.output_filename or not Path(twopass.output_filename).exists()):
                    # If merge requested but loop failed/file missing
                    if twopass.message: twopass.message += " Downmix skipped."
                    else: twopass.message = "Encoding failed. Downmix skipped."

            return render_template(
                "web.html",
                file_url=url_for("static", filename=path.name),
                twopass=twopass,
                approx=approx,
            )

        threading.Thread(target=open_browser, args=[port], name="Open Browser").start()
        app.run("0.0.0.0", port=port)
    else:
        twopass_loop(twopass=twopass, target_filesize=twopass.target_filesize, approx=approx)

        # <<< Conditionally run downmix >>>
        # Check if loop likely succeeded and merge requested via CLI flag
        if twopass.output_filename and Path(twopass.output_filename).exists() and run_amerge:
             twopass.downmix_audio() # Call the method
        elif run_amerge: # If merge was requested but loop failed/file missing
             if twopass.message: # Append to existing message if possible
                  twopass.message += " Downmix skipped."
             else: # Set message if encoding failed silently
                  twopass.message = "Encoding failed. Downmix skipped."

        print(twopass.message)


if __name__ == "__main__":
    main()