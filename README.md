# Target File Size Video Compression for Discord using `ffmpeg`
This repository houses scripts and applications to assist with compressing a video file to a desired size. 

The `ffmpeg4discord.py` script takes a video file as its input and encodes it to be less than 8MB unless specified otherwise. Discord's free-tier file size sharing limit is 8MB. You can change the file's name in a way that trims the file to a timestamped section. I created this script to share large NVIDIA ShadowPlay clips on Discord quickly, without the need for a visual editor. 

The `TwoPass()` Class showcases a 2-pass encoding methodology for the `ffmpeg-python` library, which is not well-documented on the web. The Class also supports a few ffmpeg video filters, like cropping and resolution scaling. It can be used in a variety of different audio/video workflows.

## Usage
You must first have `ffmpeg` installed on your system. `ffmpeg` needs to be registered in your PATH.

Install the required Python packages, which includes `ffmpeg-python`, with:

```pip install -r requirements.txt```

That command will

Call the script with:

```python "C:/path/to/ffmpeg4discord.py" cool_clip.mp4```

The included Batch file for Windows users, `encode.bat`, allows for drag and drop functionality. Be sure to edit the Batch file before dragging your video files on top of it.

### Special install instructions for Windows users

If you do not have ffmpeg installed, you can use the included `windows_setup.py` file to do about 90% of the installation.

```python windows_setup.py```

This script downloads ffmpeg, extracts it into the current directory, and launches the Windows Environment Variable editor dialog. Follow the instructions printed out by the script. Don't worry, you got this.

## File name formatting
1) `000020.mp4`
    - This clips and compresses the video from 00:00:20 to the end of the clip.
2) `000020-000145.mp4`
    - This clips and compresses the video from 00:00:20 to 00:01:45.
3) `SomethingElse.mp4`
    - Compresses the entire video if the first six characters of the file's name aren't numeric.

## Optional Arguments
- `-o`, `--output`
  - default: the current working directory
  - If there is a folder that you want all of your smaller clips to land in, specify it with this argument.
- `-s`, `--filesize`
  - default: `8.0`
  - Increase or decrease this value if you want to compress your video to something other than the 8MB Discord limit.
- `-a`, `--audio-br`
  - You can change this value if you want to increase or decrease your audio bitrate. Lowering it will allow for a slight increase in the compressed file's video bitrate.
- `-r`, `--resolution`
  - Example: `1280x720`
  - Modify this value to change the output resolution of your video file. I'd recommend lowering your output resolution by 1.5x or 2x. Example: `1920x1080` video should get an output resolution of `1280x720`
- `-x`, `--crop`
  - Example: `255x0x1410x1080`
  - From the top-left of your video, this example goes 255 pixels to the right, 0 pixels down, and it carves out a 1410x1080 section of the video.
  - [ffmpeg crop documentation](https://ffmpeg.org/ffmpeg-filters.html#Examples-61)
- `--config`
  - Example: `custom_run_config.json`
  - Path to a json file containing the configuration for the above parameters. This config file takes precedence over all of the other flags.

### JSON Configuration
If your encoding job will always be the same, you can reference a JSON configuration file instead of passing a long list of arguments to the command line.

```
{
    "target_filesize": 8.0,
    "audio_br": 96,
    "crop": "",
    "resolution": "",
    "codec": "libx264",
    "times": {
        "from": "00:00:00",
        "to": "00:00:40"
    }
}
```

Notes:
- All of the keys except for `"from"` and `"to"` must always be present. Those entries can be deleted if you do not have a timestamp entry for the given field. Examples: 
  - `"times": {}` -> if you do not wish to trim the start and stop time of the file. This falls back to the [file name formatting](https://github.com/zfleeman/ffmpeg4discord#file-name-formatting).
  - `"times": {"from": "00:00:10"}` -> trim the clip from `00:00:10` to the end of the file
  - `"times": {"to": "00:00:20"}` -> trim the clip from the beginning of the file up to `00:00:20`
- You can set `audio_br` to `null` if you want to maintain the clips audio bitrate.

## Docker Usage

Using the docker image is very similar to the basic python example, above. You need to volume mount your input file and the output directory. The output directory is hard coded into the Dockerfile's `ENTRYPOINT` line as the `/usr/app/out/` directory in the container. After the `docker run` options and flags, you need to specify your file name and the optional flags specified in the Python example, above.

```
docker run \
    -v /Users/zfleeman/Desktop/000100.mp4:/usr/app/000100.mp4 \
    -v /Users/zfleeman/Desktop:/usr/app/out \
    --rm zachfleeman/ffmpeg4discord:latest \
    000100.mp4 -s 20 -r 1280x720
```

If you want to use a JSON configuration file, be sure to mount it into your container.

## Detailed Example

```
python D:/ffmpeg4discord/ffmpeg4discord.py 000050-000145.mp4 \
    -c 1280x0x2560x1440 \
    -r 1920x1080 \
    -s 50 \
    -a 48 \
    -o D:/shadowplay/
```

The example above takes a 5120x1440 resolution video as its input. The script trims the video from 00:00:50 to 00:01:45 (specified in the [file name](https://github.com/zfleeman/ffmpeg4discord#file-name-formatting)). It crops a 2560x1440 section starting at 1280 pixels from the top-left and 0 pixels down (`-c`). The output file will be located in `D:/shadowplay/` (`-o`) with a new resolution of 1920x1080 (`-r`), and it will be 50MB (`-s`). The audio bitrate will be reduced to 48k (`-a`) as well, but that's probably going to sound terrible.

![](https://i.imgur.com/WJXA723.png)
