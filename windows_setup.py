from urllib.request import urlretrieve
import zipfile
import subprocess
import os

curdir = os.getcwd()

print("Downloading ffmpeg to ffmpeg.zip...")
urlretrieve("https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip", "ffmpeg.zip")
print("Done!")

print("Unzipping ffmpeg.zip...")
with zipfile.ZipFile("ffmpeg.zip", 'r') as zip_ref:
    zip_ref.extractall()
    folder = f"{curdir}\\{zip_ref.namelist()[0][:-1]}\\bin"
print("Done!")

def add_to_system_path(directory) -> None:
    # Get the current system-wide PATH
    current_path = os.environ.get('PATH', '')

    if "ffmpeg" in current_path:
        print("ffmpeg is already present in your system PATH!")
        return

    # Append the new directory to the PATH, separated by a semicolon
    new_path = f"{current_path};{directory}"

    # Set the modified PATH variable for the current session
    os.environ['PATH'] = new_path

    try:
        # Use setx command to set the PATH persistently
        subprocess.run(['setx', 'PATH', new_path], check=True)
        print(f"Added {directory} to the system-wide PATH permanently.")
    except subprocess.CalledProcessError as e:
        print(f"Failed to set the PATH permanently: {e}")

directory_to_add = folder
add_to_system_path(directory_to_add)
