from argparse import ArgumentParser, Namespace, BooleanOptionalAction


def get_args() -> Namespace:
    parser = ArgumentParser(
        prog="ffmpeg4discord",
        description="Video compression script.",
        epilog="Compress those sick clips, boi.",
    )
    parser.add_argument("filename", help="The full file path of the file that you wish to compress.")
    parser.add_argument(
        "-o",
        "--output-dir",
        default="",
        help="The desired output directory where the file will land.",
    )
    parser.add_argument(
        "-s",
        "--target-filesize",
        default=8,
        type=float,
        help="The output file size in MB. Free Discord accepts a max of 8MB.",
    )
    parser.add_argument("-a", "--audio-br", type=float, default=96, help="Audio bitrate in kbps.")

    # video filters
    parser.add_argument("-x", "--crop", default="", help="Cropping dimensions. Example: 255x0x1410x1080")
    parser.add_argument("-r", "--resolution", default="", help="The output resolution of your final video.")

    # configuraiton json file
    parser.add_argument("--config", help="JSON file containing the run's configuration")

    # installer
    parser.add_argument("--install", action=BooleanOptionalAction)

    # web
    parser.add_argument("--web", action=BooleanOptionalAction)
    parser.add_argument("-p", "--port", type=int, default=5333, help="Local port for the Flask application.")

    return vars(parser.parse_args())
