# ffmpeg video conversion for Discord
This is a Python script that takes an `.mp4` file as its input and encodes it to be less than 8MB unless specified otherwise. You can change the file's name to trim the clip to a desired section. This is especially useful in conjunction with large NVIDIA ShadowPlay clips.

This script showcases 2-pass encoding for `ffmpeg-python` library, which has historically not been well-documented on the web.

## Usage
You must first have `ffmpeg` installed on your system. `ffmpeg` also needs to be registered in your PATH.

Install the required Python package, `ffmpeg-python` with 

```pip install ffmpeg-python```

and then you can finally call the script with:

```python "C:/path/to/discord.py" cool_clip.mp4```

The included Batch file for Windows users, `encode.bat`, allows for drag and drop functionality. Be sure to edit the Batch file before dragging your video files on top of it.

## File name formatting
1) `000020.mp4`
    - This clips and compresses the video from 00:00:20 to the end of the file.
2) `000020-000145.mp4`
    - This clips and compresses the video from 00:00:20 to 00:01:45.
3) `SomethingElse.mp4`
    - Compresses the entire video. As long as the first six characters of your file's name aren't all numeric (basically, the first six characters in #1's file name), you're good.

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
  - default: `1280x720`
  - Modify this value to change the output resolution of your video file. Currently, the script only works with 16:9 aspect ratios.

