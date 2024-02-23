from argparse import ArgumentParser, Namespace, BooleanOptionalAction


def get_args() -> Namespace:
    parser = ArgumentParser(
        prog="ffmpeg4discord",
        description="This script takes a video file and compresses it to a target file size.",
        epilog="For more help: https://github.com/zfleeman/ffmpeg4discord",
    )
    parser.add_argument("filename", help="The file path of the file that you wish to compress.", required=True)
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
    parser.add_argument("-p", "--port", type=int, default=5333, help="Local port for the Flask application.")

    return vars(parser.parse_args())
