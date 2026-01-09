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


def build_parser() -> ArgumentParser:
    """
    Builds and returns the argument parser for ffmpeg4discord.
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
        "-c",
        "--codec",
        type=str,
        default="x264",
        choices=["x264", "h264_nvenc", "x265", "hevc_nvenc", "vp9", "av1"],
        help="Video codec.",
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
    # audio filters
    parser.add_argument("-an", "--no-audio", dest="no_audio", action="store_true", default=False)
    parser.add_argument(
        "--amix",
        action=BooleanOptionalAction,
        default=False,
        help="Mix all audio streams into one (default: off).",
    )
    parser.add_argument(
        "--amix-normalize",
        action=BooleanOptionalAction,
        default=False,
        help=("When mixing audio, normalize volume levels (default: off). " "Specifying this flag implies --amix."),
    )
    parser.add_argument(
        "--astreams",
        type=str,
        default=None,
        help=(
            "Comma-separated list of 0-based audio stream indexes to include in the output (e.g. '0,1,2'). "
            "If omitted, all audio streams are used."
        ),
    )
    # configuraiton json file
    parser.add_argument("--config", help="JSON file containing the run's configuration")
    # web
    parser.add_argument(
        "--web", action=BooleanOptionalAction, default=False, help="Launch ffmpeg4discord's Web UI in your browser."
    )
    parser.add_argument("-p", "--port", type=int, help="Local port for the Flask application.")
    return parser


def _normalize_amix_args(args: dict) -> dict:
    """Make --amix-normalize imply --amix, unless amix was explicitly set false."""
    # If user/config turned on normalize but never explicitly disabled amix,
    # treat that as "we are mixing, with normalization".
    if args.get("amix_normalize") and not args.get("amix"):
        args["amix"] = True
    return args


def _merge_config_args(args: dict, parser: ArgumentParser) -> dict:
    """
    Merge config file values into args if present and not already set.
    Always remove 'config' key from args.
    """
    if args.get("config"):
        file_path = Path(args["config"]).resolve()
        config = load_config(file_path)
        update_args_from_config(args, config, parser)
    args.pop("config", None)
    return args


def _assign_port(args: dict) -> dict:
    """
    Assign a port for the web UI, ensuring it is not in use.
    """
    if args.get("web"):
        port = args.pop("port") or randint(5000, 6000)
        while is_port_in_use(port):
            logging.warning(f"Port {port} is already in use. Retrying with a new port.")
            port = randint(5000, 6000)
        args["port"] = port
    else:
        args.pop("port", None)
    return args


def _extract_times(args: dict) -> dict:
    """
    Move 'from' and 'to' arguments into a 'times' dictionary.
    """
    args["times"] = {}
    if args.get("from"):
        args["times"]["from"] = args["from"]
    if args.get("to"):
        args["times"]["to"] = args["to"]
    args.pop("from", None)
    args.pop("to", None)
    return args


def _parse_astreams(args: dict) -> dict:
    """Parse --astreams from comma-separated string (or list) into a list[int] or None."""

    raw = args.get("astreams")
    if raw is None:
        return args

    # Allow config/json to provide a list already.
    if isinstance(raw, list):
        try:
            parsed = [int(x) for x in raw]
        except (TypeError, ValueError):
            logging.error("Invalid astreams list. Expected list of ints.")
            args["astreams"] = None
            return args
    else:
        raw_str = str(raw).strip()
        if raw_str == "":
            args["astreams"] = None
            return args

        parts = [p.strip() for p in raw_str.split(",") if p.strip() != ""]
        try:
            parsed = [int(p) for p in parts]
        except ValueError:
            logging.error(
                dedent(
                    """\033[31m
                    Invalid --astreams format.

                    Provide a comma-separated list of integers, e.g. --astreams "0,1,2".
                    Ignoring --astreams.
                    \033[0m"""
                )
            )
            args["astreams"] = None
            return args

    # Normalize: remove duplicates, preserve order.
    seen: set[int] = set()
    normalized: list[int] = []
    for idx in parsed:
        if idx < 0:
            logging.warning(f"Ignoring negative audio stream index in --astreams: {idx}")
            continue
        if idx in seen:
            continue
        seen.add(idx)
        normalized.append(idx)

    args["astreams"] = normalized
    return args


def get_args() -> dict:
    """
    Parses command-line arguments and returns them as a dictionary.

    Returns:
        dict: The parsed command-line arguments.
    """
    parser = build_parser()
    args = vars(parser.parse_args())
    args = _merge_config_args(args, parser)
    args = _assign_port(args)
    args = _extract_times(args)
    args = _parse_astreams(args)
    args = _normalize_amix_args(args)
    return args
