# ffmpeg video conversion for Discord
This is a Python script that takes an `.mp4` file as its input and encodes it to be less than 8MB unless specified otherwise. You can change the file's name in a way that trims the file to a timestamped section. This script is useful when sharing large NVIDIA ShadowPlay clips quickly, without the need for a visual editor.

This script showcases a 2-pass encoding methodology for the `ffmpeg-python` library, which is not well-documented on the web.

## Usage
You must first have `ffmpeg` installed on your system. `ffmpeg` also needs to be registered in your PATH.

Install the required Python package, `ffmpeg-python` with:

```pip install ffmpeg-python```

Call the script with:

```python "C:/path/to/discord.py" cool_clip.mp4```

The included Batch file for Windows users, `encode.bat`, allows for drag and drop functionality. Be sure to edit the Batch file before dragging your video files on top of it.

## File name formatting
1) `000020.mp4`
    - This clips and compresses the video from 00:00:20 to the end of the clip.
2) `000020-000145.mp4`
    - This clips and compresses the video from 00:00:20 to 00:01:45.
3) `SomethingElse.mp4`
    - Compresses the entire video if the first six characters of the file's name aren't numeric.

## Optional Arguments
- `-o`, `--output`
  - default: `current working directory`
  - If there is a folder that you want all of your smaller clips to land in, specify it with this argument.
- `-s`, `--filesize`
  - default: `8.0`
  - Increase or descrease this value if you want to compress your video to something other than the 8MB Discord limit.
- `-a`, `--audio-br`
  - default: `96`
  - You can change this value if you want to increase or decrease your audio bitrate. Lowering it will allow for a slight increase in the compressed file's video bitrate.
- `-r`, `--resolution`
  - Modify this value to change the output resolution of your video file. I'd recommend lowering your output resolution by 1.5 or 2x. Example: `1920x1080` video should get an output resolution of `1280x720`
- `-c`, `--crop`
  - Example: `255x0x1410x1080`
  - From the top-left of your video, this example goes 255 pixels to the right, 0 pixels down, and it carves out a 1410x1080 section of the video.
  - [ffmpeg crop documentation](https://ffmpeg.org/ffmpeg-filters.html#Examples-61)

