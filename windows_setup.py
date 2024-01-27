# I know this is sloppy and kind of sucks, but I figured it would help installation at least a little bit.

from urllib.request import urlretrieve
import zipfile
import subprocess
import os
import pyperclip

# Get the current system-wide PATH
current_path = os.environ.get("PATH", "")

if "ffmpeg" in current_path:
    raise SystemExit("ffmpeg is already present in your system PATH!")

curdir = os.getcwd()

print("Downloading ffmpeg to ffmpeg.zip...")
urlretrieve("https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip", "ffmpeg.zip")
print("Done!\n")

print("Unzipping ffmpeg.zip...")
with zipfile.ZipFile("ffmpeg.zip", "r") as zip_ref:
    zip_ref.extractall()
    folder = f"{curdir}\\{zip_ref.namelist()[0][:-1]}\\bin"
print("Done!\n")

pyperclip.copy(folder)
print(f"'{folder}' has been copied to your clipboard.\n")

print("Launching environment variable editor.")
print("Add the copied ffmpeg folder path as an entry to the already-existing Path variable in the editor.")
print("Click the 'Ok' buttons to exit the dialog after you're done.")

subprocess.run(["rundll32", "sysdm.cpl,EditEnvironmentVariables"], check=True)

print("\nOpen a new Terminal window and type ffmpeg and hit enter to verify that the installation succeeded.")
