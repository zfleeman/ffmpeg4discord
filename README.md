# `ff4d` -- Target File Size Video Compression for Discord with FFmpeg
This repository houses scripts and applications to assist with compressing a video file to a desired size. 

`ff4d` takes a video file as its input and encodes it to be less than 25MB unless specified otherwise. Discord's free-tier file size sharing limit is 25MB. You can change the file's name in a way that trims the file to a timestamped section. I created this package to share large NVIDIA ShadowPlay clips on Discord quickly, without the need for a visual editor. 

The `TwoPass()` Class showcases a 2-pass encoding methodology for the `ffmpeg-python` library, which is not well-documented on the web. The Class also supports a few FFmpeg video filters, like cropping and resolution scaling. It can be used in a variety of different audio/video workflows.

## Installation

This package works with Python >= 3.8. For Windows users, ensure that Python is added to your system's PATH. I highly recommend that you use the [python.org](https://python.org) Python installation.

Install this package with the following command.

```
pip install ffmpeg4discord
```

You must first have FFmpeg installed on your system. `ffmpeg` needs to be registered in your PATH. macOS or Linux users can use their favorite package manager to do this, but this process is a little more tricky for Windows users.

### Help for Windows users

After installing this package, Windows users can run this command in a terminal to download the necessary `ffmpeg` binaries:

```
install-ffmpeg-windows
```

This will place `ffmpeg.exe`, `ffprobe.exe`, and `ffplay.exe` into the same location as your Python executable.

## Usage

Run the program with:

```
ff4d cool_clip.mp4
```

I've had a good time using this command with a Batch file on Windows. Refer to the [Sample Batch File](https://github.com/zfleeman/ffmpeg4discord#sample-batch-file) section for more information.

### File name formatting

You can edit the name of your video file if you need to trim it to a specific section. Here are a few examples.

1) `000020.mp4`
    - This trims and compresses the video from 00:00:20 to the end of the clip.
2) `000020-000145.mp4`
    - This trims and compresses the video from 00:00:20 to 00:01:45.
3) `SomethingElse.mp4`
    - Compresses the entire video if the first six characters of the file's name aren't numeric.

### Optional Arguments
- `-o`, `--output`
  - default: the current working directory
  - If there is a folder that you want all of your smaller clips to land in, specify it with this argument.
- `-s`, `--filesize`
  - default: `25.0`
  - Increase or decrease this value if you want to compress your video to something other than the 25MB Discord limit.
- `-a`, `--audio-br`
  - You can change this value if you want to increase or decrease your audio bitrate. Lowering it will allow for a slight increase in the compressed file's video bitrate.
- `-r`, `--resolution`
  - Example: `1280x720`
  - Modify this value to change the output resolution of your video file. I'd recommend lowering your output resolution by 1.5x or 2x. Example: `1920x1080` video should get an output resolution of `1280x720`
- `-x`, `--crop`
  - Example: `255x0x1410x1080`
  - From the top-left of your video, this example goes 255 pixels to the right, 0 pixels down, and it carves out a 1410x1080 section of the video.
  - [FFmpeg crop documentation](https://ffmpeg.org/ffmpeg-filters.html#Examples-61)
- `--web`
  - Launch the Web UI for this job. A Boolean flag. No value is needed after the flag. See [Web UI](#web-ui) for more information on the Web UI.
- `-p`, `--port`
  - Example: `5333`
  - Run the Web UI on a specifc port.
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
- You can set `audio_br` to `null` if you want to maintain the clip's audio bitrate.

## Detailed Example

```
ff4d 000050-000145.mp4 \
    -x 1280x0x2560x1440 \
    -r 1920x1080 \
    -s 50 \
    -a 48 \
    -o D:/shadowplay/
```

The example above takes a 5120x1440 resolution video as its input. The script trims the video from 00:00:50 to 00:01:45 (specified in the [file name](https://github.com/zfleeman/ffmpeg4discord#file-name-formatting)). It crops a 2560x1440 section starting at 1280 pixels from the top-left and 0 pixels down (`-x`). The output file will be located in `D:/shadowplay/` (`-o`) with a new resolution of 1920x1080 (`-r`), and it will be 50MB (`-s`). The audio bitrate will be reduced to 48k (`-a`) as well, but that's probably going to sound terrible.

![](https://i.imgur.com/WJXA723.png)

## Web UI

The web UI can be activated by adding `--web` to your `ff4d` call.

```
ff4d cool_clip.mp4 -r 1280x720 -s 20 --web
```

That command will spin up a Flask server on your local machine and launch a rendered webpage with the video as the centerpiece. The flags you provide to `ff4d` will fill in the defaults for the form. You can override/replace the values.

You can drag the video playhead to different portions of the video and click the "Set Start/End Time" buttons to specify the section of the video you want to be clipped out. You can also use the range sliders underneath the buttons if you prefer. A "Preview Selection" button is provided for your convenience, and it does what it sounds like.

https://github.com/zfleeman/ffmpeg4discord/assets/1808564/ff323bcb-4747-437b-808f-ce48b8c269ce

The Flask server doesn't automatically stop itself, so you'll have to terminate it manually by closing the terminal it leaves hanging.

## Sample Batch File

To enable "drag and drop" functionality for this package, Windows users can create a `.bat` file with the following code snippet. Once the file is created, you can drag and drop any `.mp4` file on top of it, and it will run with the flags specified in the "[Optional Arguments](https://github.com/zfleeman/ffmpeg4discord#file-name-formatting)" section. This example is a Batch file that will launch the web UI.

```batch
@echo off
Set filename=%1
ff4d %filename% -o "C:/output/folder/" --web
DEL "ffmpeg2*"
PAUSE
```

## Thanks!

Yes, this is a simple collection of Python files using FFmpeg tricks that is masquerading as a robust Audio/Video tool. But! I use this nearly every day to quickly share videos with people on various messaging apps that have built-in video players. I don't have to share a link that embeds a video player this way, and I guess that's important to me?

I like working on this! Enjoy!
