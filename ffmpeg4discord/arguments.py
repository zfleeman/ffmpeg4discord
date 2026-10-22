"""Reads ff4d's command-line flags and config files."""

import json
import logging
import socket
import sys
from argparse import ArgumentParser, BooleanOptionalAction
from pathlib import Path
from random import randint

import platformdirs

from ffmpeg4discord.twopass import FALLBACK_AUDIO_BR, available_codecs


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
    parser.add_argument(
        "--dry-run",
        action=BooleanOptionalAction,
        default=False,
        help="Print the FFmpeg commands for the first encode attempt without running them. Ignored with --web.",
    )
    parser.add_argument(
        "--from",
        help="Start clipping at this timestamp, seconds, or percentage of the video, e.g. 00:00:10.5, 90, or 75%%",
    )
    parser.add_argument(
        "--to",
        help="Stop clipping at this timestamp, seconds, or percentage of the video, e.g. 00:00:20.25, 95, or 95%%",
    )
    parser.add_argument(
        "-s",
        "--target-filesize",
        default=20,
        type=float,
        help="The output file size in MB.",
    )
    parser.add_argument("-a", "--audio-br", type=float, default=FALLBACK_AUDIO_BR / 1000, help="Audio bitrate in kbps.")
    parser.add_argument(
        "-c",
        "--codec",
        type=str,
        default="x264",
        choices=available_codecs(),
        help="Video codec. VideoToolbox codecs are only listed on macOS.",
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
    parser.add_argument(
        "-r",
        "--resolution",
        default="",
        help="The output resolution of your final video.",
    )
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
        help=("When mixing audio, normalize volume levels (default: off). Specifying this flag implies --amix."),
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
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--config", help="JSON file containing the run's configuration")
    group.add_argument(
        "--no-config",
        action="store_true",
        default=False,
        help="Do not attempt to read any default configuration files (default: off)",
    )
    # web
    parser.add_argument(
        "--web",
        action=BooleanOptionalAction,
        default=False,
        help="Launch ffmpeg4discord's Web UI in your browser.",
    )
    parser.add_argument("-p", "--port", type=int, help="Local port for the Flask application.")
    return parser


def _search_for_default_config(args: dict) -> dict:
    """
    Search for config files in platform-specific default locations and include them
    if they exist (unless the --no-config flag is used)
    """
    if args.get("config") is None and not args.get("no_config"):
        if sys.platform == "linux":  # allow for ~/.config/ffmpeg4discord.json under linux
            conf = platformdirs.user_config_path() / "ffmpeg4discord.json"
            logging.info(f"checking for {conf}")
            if conf.exists() and conf.is_file():
                args["config"] = conf
                return args

        conf = platformdirs.user_config_path("ffmpeg4discord") / "ffmpeg4discord.json"
        logging.info(f"checking for {conf}")
        if conf.exists() and conf.is_file():
            logging.info(f"default config file found at {conf}")
            args["config"] = conf
            return args

        logging.info("no default configuration files found")

    return args


def _merge_config_args(args: dict, parser: ArgumentParser, argv: list[str] | None = None) -> dict:
    """
    Make the config file's values the parser's defaults, then parse the command line again.
    Flags typed on the command line beat the config file, even when they match a built-in default.
    Always remove 'config' key from args.
    """
    configs = set()
    defaults = {}
    while args.get("config") is not None:
        file_path = Path(args.pop("config")).resolve()
        if file_path not in configs:
            configs.add(file_path)
            config = load_config(file_path)
            args["config"] = config.get("config")
            defaults = {**config, **defaults}  # a config file beats the one it points to
    if defaults:
        parser.set_defaults(**defaults)
        args = vars(parser.parse_args(argv))
    args.pop("config", None)
    args.pop("no_config", None)
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
    Rename the 'from' and 'to' arguments to 'start' and 'end', the `EncodeSettings` names. `from` is a Python keyword.
    """
    args["start"] = args.pop("from", None) or None
    args["end"] = args.pop("to", None) or None
    return args


def _parse_astreams(args: dict) -> dict:
    """Turn --astreams, e.g. "0,2", into a list of track numbers. A config file can also give a list, e.g. [0, 2]."""
    raw = args.get("astreams")
    if raw is None or raw == "":
        args["astreams"] = None  # use every audio track
        return args

    parts = [str(part).strip() for part in (raw if isinstance(raw, list) else str(raw).split(","))]
    # isdecimal() is False for negative numbers, decimals, and blanks
    if not all(part.isdecimal() for part in parts):
        raise ValueError(
            f"Invalid --astreams value {raw!r}. Use audio track numbers starting at 0, separated by commas, e.g. 0,2."
        )

    args["astreams"] = list(dict.fromkeys(int(part) for part in parts))  # removes duplicates, keeps the order
    return args


def get_args() -> dict:
    """
    Parses command-line arguments and returns them as a dictionary.

    Returns:
        dict: The parsed command-line arguments.
    """
    parser = build_parser()
    args = vars(parser.parse_args())
    args = _search_for_default_config(args)
    args = _merge_config_args(args, parser)
    args = _assign_port(args)
    args = _extract_times(args)
    args = _parse_astreams(args)
    # Normalizing only applies to mixed audio, so --amix-normalize turns on --amix
    if args.get("amix_normalize"):
        args["amix"] = True
    return args
