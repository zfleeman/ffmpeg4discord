from argparse import ArgumentParser, Namespace

def get_args() -> Namespace:
    # args work
    parser = ArgumentParser(
        prog="ffmpeg4discord",
        description="Video compression script.",
        epilog="Compress those sick clips, boi.",
    )

    parser.add_argument(
        "filename", help="The full file path of the file that you wish to compress."
    )

    parser.add_argument(
        "-o",
        "--output",
        default="",
        help="The desired output directory where the file will land.",
    )

    parser.add_argument(
        "-s",
        "--filesize",
        default=8.0,
        type=float,
        help="The output file size in MB. Free Discord accepts a max of 8MB.",
    )

    parser.add_argument(
        "-a", "--audio-br", default=96, type=float, help="Audio bitrate in kbps."
    )

    # video filters
    parser.add_argument(
        "-c", "--crop", help="Cropping dimensions. Example: 255x0x1410x1080"
    )
    parser.add_argument(
        "-r", "--resolution", help="The output resolution of your final video."
    )

    return parser.parse_args()
