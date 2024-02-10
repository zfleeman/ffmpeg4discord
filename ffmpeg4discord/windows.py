import sys
import os
from urllib.request import urlretrieve
import zipfile
from pathlib import Path
import shutil
import logging

logging.getLogger().setLevel(logging.INFO)

path = os.environ.get("PATH", "")
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
        downloaded_mb = downloaded / (1024 * 1024)
        total_size_mb = total_size / (1024 * 1024)
        progress = min(downloaded / total_size, 1.0)
        percent = round(progress * 100, 2)
        print(f"\rDownloaded {downloaded_mb:.2f}/{total_size_mb:.2f} MB ({percent}%)", end="")

    save_dir = Path(save_path).parent
    save_dir.mkdir(parents=True, exist_ok=True)

    urlretrieve(url, save_path, reporthook=report)
    print("\nDownload complete!")


def setup():
    print("Downloading ffmpeg to ffmpeg.zip...")
    download_with_progress("https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip", "ffmpeg/ffmpeg.zip")

    print("\nUnzipping ffmpeg.zip...")
    with zipfile.ZipFile("ffmpeg/ffmpeg.zip", "r") as zip_ref:
        zip_ref.extractall("ffmpeg/")
        source = Path(f"ffmpeg/{zip_ref.namelist()[0]}/bin").resolve()
    print("Done!\n")

    copy_directory_contents(source=source, target=target)
    shutil.rmtree("ffmpeg/")

    print("\nffmpeg installation complete.")
    print("\nOpen a new Terminal window and type ffmpeg and hit enter to verify that the installation succeeded.")


if __name__ == "__main__":
    setup()
