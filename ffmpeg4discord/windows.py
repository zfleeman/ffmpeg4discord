"""
This module provides functions for downloading and installing FFmpeg on Windows systems.
This file may not be well-maintained. Use with caution.

It includes functions to check the Python installation, download FFmpeg with a progress indicator,
unzip the downloaded files, and copy the necessary files to the appropriate directory.

Functions:
- copy_directory_contents: Copies the contents of one directory to another.
- download_with_progress: Downloads a file from a URL with a progress indicator.
- install: Downloads, unzips, and installs FFmpeg on a Windows system.
"""

import logging
import os
import platform
import shutil
import sys
import zipfile
from pathlib import Path
from textwrap import dedent
from urllib.request import urlretrieve

if platform.system() != "Windows":
    logging.warning(
        dedent(
            """\033[31m
            THIS SCRIPT IS INTENDED FOR WINDOWS USERS

            If you are running this script on macOS, consider installing ffmpeg with
            Homebrew: https://formulae.brew.sh/formula/ffmpeg

            If you are running this script on some Linux, learn more about your options
            to install ffmpeg on its website: https://ffmpeg.org/download.html#build-linux
            \033[0m"""
        )
    )

    sys.exit()

logging.getLogger().setLevel(logging.INFO)

path = os.environ.get("PATH", "")
python_install = Path(sys.executable)

if "WindowsApps" in str(python_install):
    print(
        dedent(
            """
            Microsoft Store Python installation detected. 
            If you run into problems, consider using the https://python.org installation instead!
            """
        )
    )
    target = Path(sys.executable).parent.parent
else:
    print("python.org Python installation detected.")
    target = Path(sys.executable).parent / "Scripts"

target.mkdir(parents=True, exist_ok=True)

if str(target) not in path:
    logging.warning(
        """
        The directory we are installing ffmpeg into is not in your 
        system's PATH. Windows will not be able to find ffmpeg when 
        trying to run ffmpeg4discord. Please ensure that you installed 
        Python with the "Add Python to PATH" option selected.
        
        More information: https://docs.python.org/3/using/windows.html#finding-the-python-executable
        """
    )


def copy_directory_contents(source_path: Path, target_path: Path) -> None:
    """
    Copies the contents of one directory to another.

    Args:
        source (Path): The source directory.
        target (Path): The target directory.
    """

    # Iterate over files in the source directory
    for item in source_path.iterdir():
        # Construct target item path
        target_item = target_path / item.name

        # If the item is a file, copy it to the target directory
        if item.is_file():
            shutil.copy2(item, target_item)
            print(f"Copied file: {item} -> {target_item}")


def download_with_progress(url: str, save_path: str) -> None:
    """
    Downloads a file from a URL with a progress indicator.

    Args:
        url (str): The URL to download the file from.
        save_path (str): The path to save the downloaded file.
    """

    def report(block_num, block_size, total_size):
        downloaded = block_num * block_size
        downloaded_mb = downloaded / (1024 * 1024)
        total_size_mb = total_size / (1024 * 1024)
        progress = min(downloaded / total_size, 1.0)
        percent = round(progress * 100, 2)
        print(f"\rDownloaded {downloaded_mb:.2f}/{total_size_mb:.2f} MB ({percent}%)", end="")

    save_dir = Path(save_path).parent
    save_dir.mkdir(parents=True, exist_ok=True)

    urlretrieve(url, save_path, reporthook=report)
    print("\nDownload complete!")


def install() -> None:
    """
    Downloads, unzips, and installs FFmpeg on a Windows system.
    """
    print("Downloading ffmpeg to ffmpeg.zip...")
    download_with_progress("https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip", "ffmpeg/ffmpeg.zip")

    print("\nUnzipping ffmpeg.zip...")
    with zipfile.ZipFile("ffmpeg/ffmpeg.zip", "r") as zip_ref:
        zip_ref.extractall("ffmpeg/")
        source = Path(f"ffmpeg/{zip_ref.namelist()[0]}/bin").resolve()
    print("Done!\n")

    copy_directory_contents(source_path=source, target_path=target)
    shutil.rmtree("ffmpeg/")

    print("\nffmpeg installation complete.")
    print("\nOpen a new Terminal window and type ffmpeg and hit enter to verify that the installation succeeded.")


if __name__ == "__main__":
    install()
