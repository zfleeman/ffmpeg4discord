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
from ffmpeg4discord.twopass import TwoPass, seconds_to_timestamp


def twopass_loop(twopass: TwoPass, target_filesize: float, approx: bool = False) -> None:
    while twopass.run() >= target_filesize and not approx:
        print(
            f"\nThe output file size ({round(twopass.output_filesize, 2)}MB) is still above the target of {target_filesize}MB.\nRestarting...\n"
        )
        os.remove(twopass.output_filename)

        # adjust the class's target file size to set a lower bitrate for the next run
        twopass.target_filesize -= 0.2

    # clean up
    for file in glob("ffmpeg2pass*"):
        os.remove(file)

    twopass.message = f"Your compressed video file ({round(twopass.output_filesize, 2)}MB) is located at {Path(twopass.output_filename).resolve()}"


def open_browser(port: int) -> None:
    time.sleep(0.5)
    webbrowser.open(f"http://localhost:{port}")


def main() -> None:
    # get args from the command line
    args = arguments.get_args()
    web = args.pop("web")
    approx = bool(args.pop("approx"))

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
            twopass.audio_br = float(request.form.get("audio_br")) * 1000
            twopass.crop = request.form.get("crop")
            twopass.output = Path(request.form.get("output"))
            twopass.codec = request.form.get("codec")
            twopass.framerate = int(request.form.get("framerate"))

            # to loop or not to loop
            approx = bool(request.form.getlist("approx"))

            twopass_loop(twopass=twopass, target_filesize=target_filesize, approx=approx)

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
        print(twopass.message)


if __name__ == "__main__":
    main()
