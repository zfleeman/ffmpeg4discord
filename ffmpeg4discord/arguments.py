import json
import logging
import socket

from argparse import ArgumentParser, Namespace, BooleanOptionalAction
from pathlib import Path
from random import randint


def is_port_in_use(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(("localhost", port)) == 0


def get_args() -> Namespace:
    parser = ArgumentParser(
        prog="ffmpeg4discord",
        description="This script takes a video file and compresses it to a target file size.",
        epilog="For more help: https://github.com/zfleeman/ffmpeg4discord",
    )
    parser.add_argument("filename", help="The file path of the file that you wish to compress.")
    parser.add_argument(
        "-o",
        "--output",
        default="",
        help="The desired output directory where the file will land.",
    )
    parser.add_argument(
        "--filename-times",
        action=BooleanOptionalAction,
        help="Generate From/To timestamps from the clip's file name.",
    )
    parser.add_argument(
        "--approx",
        action=BooleanOptionalAction,
        help="Approximate file size. The job will not loop to output the file under the target size. It will get close enough to the target on the first run.",
    )
    parser.add_argument("--from", help="Start clipping at this timestamp, e.g. 00:00:10")
    parser.add_argument("--to", help="Stop clipping at this timestamp, e.g. 00:00:20")
    parser.add_argument(
        "-s",
        "--target-filesize",
        default=10,
        type=float,
        help="The output file size in MB.",
    )
    parser.add_argument("-a", "--audio-br", type=float, default=96, help="Audio bitrate in kbps.")
    parser.add_argument(
        "-c", "--codec", type=str, default="libx264", choices=["libx264", "libvpx-vp9"], help="Video codec."
    )
    parser.add_argument(
        "--vp9-opts",
        type=str,
        default=None,
        help="""JSON string to configure row-mt, deadline, and cpu-used options for VP9 encoding. (e.g., --vp9-opts \'{"row-mt": 1, "deadline": "good", "cpu-used": 2}\')')""",
    )

    # video filters
    parser.add_argument("-x", "--crop", default="", help="Cropping dimensions. Example: 255x0x1410x1080")
    parser.add_argument("-r", "--resolution", default="", help="The output resolution of your final video.")
    parser.add_argument("-f", "--framerate", type=int, help="The desired output frames per second.")

    # configuraiton json file
    parser.add_argument("--config", help="JSON file containing the run's configuration")

    # web
    parser.add_argument("--web", action=BooleanOptionalAction, help="Launch ffmpeg4discord's Web UI in your browser.")
    parser.add_argument("-p", "--port", type=int, help="Local port for the Flask application.")

    args = vars(parser.parse_args())

    # fill in from the config JSON
    if args["config"]:
        file_path = Path(args["config"]).resolve()
        with open(file_path) as f:
            config: dict = json.load(f)

        for k, v in config.items():
            if not args[k]:
                args[k] = v
            elif args[k] == parser.get_default(k):
                args[k] = v

    del args["config"]

    # do some work regarding the port
    if args["web"]:
        port = args.pop("port")
        port = port if port else randint(5000, 6000)

        while True:
            if not is_port_in_use(port):
                break
            logging.warning(f"Port {port} is already in use. Retrying with a new port.")
            port = randint(5000, 6000)

        args["port"] = port
    else:
        del args["port"]

    args["times"] = {}

    # adjust times
    if args["from"]:
        args["times"]["from"] = args["from"]

    if args["to"]:
        args["times"]["to"] = args["to"]

    del args["from"]
    del args["to"]

    # work with vp9 options
    if args["vp9_opts"] and not isinstance(args["vp9_opts"], dict):
        logging.info(f"Received VP9 options: {args['vp9_opts']}")
        try:
            args["vp9_opts"] = json.loads(args["vp9_opts"])
        except json.JSONDecodeError:
            logging.error(
                """Invalid JSON format. Format your input string like this: \'{"row-mt": 1, "deadline": "good", "cpu-used": 2}\'. Using default parameters."""
            )
            args["vp9_opts"] = None

    return args
