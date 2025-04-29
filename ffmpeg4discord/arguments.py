"""
This module provides functions for parsing command-line arguments and 
loading configuration settings for the ffmpeg4discord application.

Functions:
- is_port_in_use: Checks if a given port is currently in use.
- load_config: Loads configuration settings from a JSON file.
- update_args_from_config: Updates command-line arguments with values from a configuration file.
- get_args: Parses command-line arguments and returns them as a dictionary.
"""

import json
import logging
import socket
from argparse import ArgumentParser, BooleanOptionalAction
from pathlib import Path
from random import randint
from textwrap import dedent


def is_port_in_use(port: int) -> bool:
    """
    Checks if a given port is currently in use.

    Args:
        port (int): The port number to check.

    Returns:
        bool: True if the port is in use, False otherwise.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(("localhost", port)) == 0


def load_config(file_path: Path) -> dict:
    """
    Loads configuration settings from a JSON file.

    Args:
        file_path (Path): The path to the JSON configuration file.

    Returns:
        dict: The configuration settings as a dictionary.
    """
    with open(file_path, encoding="UTF-8") as f:
        return json.load(f)


def update_args_from_config(args: dict, config: dict, parser: ArgumentParser) -> None:
    """
    Updates command-line arguments with values from a configuration file.

    Args:
        args (dict): The command-line arguments.
        config (dict): The configuration settings from the JSON file.
        parser (ArgumentParser): The argument parser instance.
    """
    for k, v in config.items():
        if not args[k] or args[k] == parser.get_default(k):
            args[k] = v


def get_args() -> dict:
    """
    Parses command-line arguments and returns them as a dictionary.

    Returns:
        dict: The parsed command-line arguments.
    """
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
        default=False,
        help="Generate From/To timestamps from the clip's file name.",
    )
    parser.add_argument(
        "--approx",
        action=BooleanOptionalAction,
        default=False,
        help="The job will not loop to output the file under the target size.",
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
        help="""JSON string to configure row-mt, deadline, and cpu-used options for VP9 encoding. (e.g., --vp9-opts \'{"row-mt": 1, "deadline": "good", "cpu-used": 2}\')')""",  # pylint: disable=C0301
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action=BooleanOptionalAction,
        default=False,
        help="Add this flag to get more detailed logging out of FFmpeg. Useful for debugging an error.",
    )

    # video filters
    parser.add_argument("-x", "--crop", default="", help="Cropping dimensions. Example: 255x0x1410x1080")
    parser.add_argument("-r", "--resolution", default="", help="The output resolution of your final video.")
    parser.add_argument("-f", "--framerate", type=int, help="The desired output frames per second.")

    # configuraiton json file
    parser.add_argument("--config", help="JSON file containing the run's configuration")

    # web
    parser.add_argument(
        "--web", action=BooleanOptionalAction, default=False, help="Launch ffmpeg4discord's Web UI in your browser."
    )
    parser.add_argument("-p", "--port", type=int, help="Local port for the Flask application.")

    # Add argument for audio merging
    parser.add_argument(
        "--amerge",
        action=BooleanOptionalAction,
        default=False,
        help="Merge all audio channels down to 1 (mono) after encoding."
    )


    args = vars(parser.parse_args())

    # fill in from the config JSON
    if args["config"]:
        file_path = Path(args["config"]).resolve()
        config = load_config(file_path)
        update_args_from_config(args, config, parser)

    del args["config"]

    # do some work regarding the port
    if args["web"]:
        port = args.pop("port") or randint(5000, 6000)
        while is_port_in_use(port):
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
                dedent(
                    """\033[31m
                    Invalid JSON format. 
                    Format your input string like this: \'{"row-mt": 1, "deadline": "good", "cpu-used": 2}\'. 
                    Using default parameters.
                    \033[0m"""
                )
            )
            args["vp9_opts"] = None

    return args
