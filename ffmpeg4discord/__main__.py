import sys
import os
from glob import glob
import webbrowser
from flask import Flask, render_template, url_for, request
import time
import threading
from pathlib import Path

sys.dont_write_bytecode = True
from ffmpeg4discord import arguments
from ffmpeg4discord.twopass import TwoPass


def twopass_loop(twopass: TwoPass, target_filesize: float) -> None:
    while twopass.run() >= target_filesize:
        print(
            f"\nThe output file size ({round(twopass.output_filesize, 2)}MB) is still above the target of {target_filesize}MB.\nRestarting...\n"
        )
        os.remove(twopass.output_filename)

        # adjust the class's target file size to set a lower bitrate for the next run
        twopass.target_filesize -= 0.2

    twopass.message = f"Your compressed video file ({round(twopass.output_filesize, 2)}MB) is located at {Path(twopass.output_filename).resolve()}"


def seconds_to_timestamp(seconds: int) -> str:
    hours, remainder = divmod(seconds, 3600)
    minutes, seconds = divmod(remainder, 60)

    # Use f-strings to format the timestamp
    timestamp = f"{hours:02d}:{minutes:02d}:{seconds:02d}"

    return timestamp


def open_browser(port: int) -> None:
    time.sleep(0.5)
    webbrowser.open(f"http://localhost:{port}")


def main() -> None:
    # get args from the command line
    args = arguments.get_args()
    web = args.pop("web")

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
                "web.html", file_url=url_for("static", filename=path.name), twopass=twopass, alert_hidden=True
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
            twopass.audio_br = float(request.form.get("audio_br")) * 1000
            twopass.crop = request.form.get("crop")
            twopass.output_dir = request.form.get("output_dir")

            twopass_loop(twopass=twopass, target_filesize=target_filesize)

            for file in glob("ffmpeg2pass*"):
                os.remove(file)

            return render_template(
                "web.html",
                file_url=url_for("static", filename=path.name),
                twopass=twopass,
            )

        threading.Thread(target=open_browser, args=[port], name="Open Browser").start()
        app.run("0.0.0.0", port=port)
    else:
        twopass_loop(twopass=twopass, target_filesize=twopass.target_filesize)
        print(twopass.message)


if __name__ == "__main__":
    main()
