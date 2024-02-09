# I know this is sloppy and kind of sucks, but I figured it would help installation at least a little bit.

import sys
from urllib.request import urlretrieve
import zipfile
from pathlib import Path
import shutil

target = Path(sys.executable).parent


def copy_directory_contents(source, target):
    source_path = Path(source)
    target_path = Path(target)

    # Iterate over files in the source directory
    for item in source_path.iterdir():
        # Construct target item path
        target_item = target_path / item.name

        # If the item is a file, copy it to the target directory
        if item.is_file():
            shutil.copy2(item, target_item)
            print(f"Copied file: {item} -> {target_item}")


def download_with_progress(url, save_path):
    def report(block_num, block_size, total_size):
        downloaded = block_num * block_size
        progress = min(downloaded / total_size, 1.0)
        percent = round(progress * 100, 2)
        print(f"\rDownloaded {downloaded}/{total_size} bytes ({percent}%)", end="")

    urlretrieve(url, save_path, reporthook=report)
    print("\nDownload complete!")


def setup():

    print("Downloading ffmpeg to ffmpeg.zip...")
    download_with_progress("https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip", "ffmpeg.zip")

    print("Unzipping ffmpeg.zip...")
    with zipfile.ZipFile("ffmpeg.zip", "r") as zip_ref:
        zip_ref.extractall()
        source = Path(f"{zip_ref.namelist()[0]}/bin").resolve()
    print("Done!\n")

    copy_directory_contents(source=source, target=target)

    print("\nffmpeg installation complete.")
    print("\nOpen a new Terminal window and type ffmpeg and hit enter to verify that the installation succeeded.")


if __name__ == "__main__":
    setup()
