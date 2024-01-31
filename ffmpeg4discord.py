import os
from utils.arguments import get_args
from twopass import TwoPass
import webbrowser
from flask import Flask, render_template, url_for
from random import randint
import time
import threading
from pathlib import Path


# get args from the command line
args = get_args()
web = args.pop("web")
path = Path(args["filename"]).resolve()
args["filename"] = path
app = Flask(__name__, static_folder=path.parent)


def twopass_loop(twopass: TwoPass):
    while twopass.run() >= end_fs:
        print(
            f"\nThe output file size ({round(twopass.output_filesize, 2)}MB) is still above the target of {end_fs}MB.\nRestarting...\n"
        )
        os.remove(twopass.output_filename)

        # adjust the class's target file size to set a lower bitrate for the next run
        twopass.target_filesize -= 0.2

    print(
        f"\nSUCCESS!!\nThe smaller file ({round(twopass.output_filesize, 2)}MB) is located at {twopass.output_filename}"
    )


def open_browser():
    time.sleep(0.5)
    webbrowser.open(f"http://localhost:{port}")


@app.route("/")
def index():
    return render_template("web.html", filename=url_for("static", filename=path.name))


if web:
    port = randint(5000, 6000)
    threading.Thread(target=open_browser, name="Open Browser").start()
    app.run("0.0.0.0", port=port)
else:
    # instantiate the TwoPass class and save our target file size for comparison in the loop
    twopass = TwoPass(**args)
    end_fs = args["target_filesize"]
    twopass_loop(twopass=twopass)
