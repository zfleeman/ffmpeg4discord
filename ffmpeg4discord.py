import os
from utils.arguments import get_args
from twopass import TwoPass
import webbrowser
from flask import Flask, render_template, url_for, request
from random import randint
import time
import threading
from pathlib import Path


# get args from the command line
args = get_args()
web = args.pop("web")
path = Path(args["filename"]).resolve()
args["filename"] = path

# instantiate the TwoPass class
twopass = TwoPass(**args)


def twopass_loop(target_filesize: float):
    while twopass.run() >= target_filesize:
        print(
            f"\nThe output file size ({round(twopass.output_filesize, 2)}MB) is still above the target of {target_filesize}MB.\nRestarting...\n"
        )
        os.remove(twopass.output_filename)

        # adjust the class's target file size to set a lower bitrate for the next run
        twopass.target_filesize -= 0.2

    print(
        f"\nSUCCESS!!\nThe smaller file ({round(twopass.output_filesize, 2)}MB) is located at {twopass.output_filename}"
    )


def seconds_to_timestamp(seconds):
    hours, remainder = divmod(seconds, 3600)
    minutes, seconds = divmod(remainder, 60)

    # Use f-strings to format the timestamp
    timestamp = f"{hours:02d}:{minutes:02d}:{seconds:02d}"

    return timestamp


def open_browser():
    time.sleep(0.5)
    webbrowser.open(f"http://localhost:{port}")


if web:
    app = Flask(__name__, static_folder=path.parent)

    @app.route("/")
    def index():
        return render_template(
            "web.html",
            filename=url_for("static", filename=path.name),
            resolution=twopass.resolution,
            target_filesize=twopass.target_filesize,
            audio_br=twopass.audio_br,
            crop=twopass.crop,
            output_dir=twopass.output_dir,
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

        twopass_loop(target_filesize)

        return f"Your compressed video file is located at <strong>{Path(twopass.output_filename).resolve()}</strong>"

    port = randint(5000, 6000)
    threading.Thread(target=open_browser, name="Open Browser").start()
    app.run("0.0.0.0", port=port)
else:
    twopass_loop(args["target_filesize"])
