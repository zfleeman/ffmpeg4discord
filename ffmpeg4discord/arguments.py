from argparse import ArgumentParser, Namespace, BooleanOptionalAction
import socket
import logging
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
        "--output-dir",
        default="",
        help="The desired output directory where the file will land.",
    )
    parser.add_argument(
        "-s",
        "--target-filesize",
        default=25,
        type=float,
        help="The output file size in MB.",
    )
    parser.add_argument("-a", "--audio-br", type=float, default=96, help="Audio bitrate in kbps.")

    # video filters
    parser.add_argument("-x", "--crop", default="", help="Cropping dimensions. Example: 255x0x1410x1080")
    parser.add_argument("-r", "--resolution", default="", help="The output resolution of your final video.")

    # configuraiton json file
    parser.add_argument("--config", help="JSON file containing the run's configuration")

    # web
    parser.add_argument("--web", action=BooleanOptionalAction, help="Launch ffmpeg4discord's Web UI in your browser.")
    parser.add_argument("-p", "--port", type=int, help="Local port for the Flask application.")

    args = vars(parser.parse_args())

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

    return args
