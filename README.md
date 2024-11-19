# ffmpeg4discord (`ff4d`) -- Target File Size Video Compression for Discord with FFmpeg
[![PyPI version](https://img.shields.io/pypi/v/ffmpeg4discord.svg)](https://pypi.org/project/ffmpeg4discord/)

`ff4d` takes a video file as its input and encodes it to be less than a target file size. Discord's free-tier file size sharing limit is 10MB. You can change the file's name in a way that trims the file to a timestamped section. I developed this package specifically for swift sharing of large NVIDIA ShadowPlay clips on Discord, eliminating the need for a visual editor.

The `TwoPass()` class presents a 2-pass encoding approach for the `ffmpeg-python` library, which is not showcased in that package's documentation. Additionally, the class extends support to various FFmpeg video filters such as cropping and resolution scaling, making it adaptable to a range of audio/video workflows.

## Installation

This package requires Python >= 3.9. For Windows users, ensure that Python is added to your system's PATH. I highly recommend that you use the [python.org](https://python.org) Python installation.

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

Use `ff4d` in your favorite terminal like this:

```
ff4d path-to-file.mp4 [optional-flags]
```

This command tries to compress the whole video file down to the an output file size of 10MB:

```
ff4d cool_clip.mp4 -s 10
```

This will trim a 20 second section out of `cool_clip.mp4` starting at 10 seconds in and ending at 30 seconds. The output will be less than 10MB. [More on the optional flags](#optional-flags).

```
ff4d cool_clip.mp4 --from 00:00:10 --to 00:00:30 -s 10
```

I've had a good time using this command with a Batch file on Windows. Refer to the [Sample Batch File](#sample-batch-file) section for more information.

### Optional Flags
| Flag | Default | Example | Description |
|---|---|---|---|
| `-o`<br>`--output` | current working directory | `-o "C:/Users/zflee/A Folder"`<br>`-o "C:/Users/zflee/Desktop/A Folder/filename.mp4"` | If you want your smaller clips to go to a specific folder, use this option. You can also choose a custom output filename, just make sure to include the correct file extension for your video codec. |
| `-s`<br>`--filesize` | 25 | `-s 50` | Change this value if you want to compress your video to something other than the 10MB Discord limit. |
| `-a`<br>`--audio-br` | 96 | `-a 128` | You can change this value if you want to increase or decrease your audio bitrate. Lowering it will allow for a slight increase in the compressed file's video bitrate. |
| `-r`<br>`--resolution` | No default | `-r 1280x720` | Modify this value to change the output resolution of your video file. |
| `-x`<br>`--crop` | No default | `-x 255x0x1410x1080` | [FFmpeg crop documentation](https://ffmpeg.org/ffmpeg-filters.html#Examples-61). From the top-left of your video, this example goes 255 pixels to the right, 0 pixels down, and it carves out a 1410x1080 section of the video. |
| `-c`<br>`--codec` | libx264 | `-c libvpx-vp9` | Options: `libx264` or `libvpx-vp9`<br>Specify the video codec that you want to use. The default option creates `.mp4` files, while `libvpx-vp9` creates `.webm` video files.<br>`libvpx-vp9` creates better looking video files with the same bitrates, but it takes significantly longer to encode. VP9 is also not as compatible with as many devices or browsers. I can view `.webm` videos on the desktop installation of Discord, but they are not viewable on my iOS Discord installation. |
| `--web` | No default. Boolean flag. | `--web` | Launch the Web UI for this job. A Boolean flag. No value is needed after the flag. See [Web UI](#web-ui) for more information on the Web UI. |
| `-p`<br>`--port` | No default. Picks a random port if not specified. | `-p 5333` | Run the Web UI on a specific port. |
| `--config` | No default | `--config config.json` | Path to a JSON file containing the configuration for the above parameters. This config file takes precedence over all of the other flags. See [JSON Configuration](#json-configuration). |
| `--from` | No default | `--from 00:01:00` | Start time for trimming the video file to a desired section. |
| `--to` | No default | `--to 00:01:20` | End time for trimming the video file to a desired section. |
| `--filename-times` | No default. Boolean flag. | `--filename-times` | Generate From/To timestamps from the clip's file name. See [File Name Formatting](#file-name-formatting) |
| `--approx` | No default. Boolean flag. | `--approx` | Approximate file size. The job will not loop to output the file under the target size. It will get close enough to the target on the first run. |
| `-f`<br>`--framerate` | No default. | `-f 30` | Adjust the output's frame rate. Specify a value lower than the input video's frame rate. |
| `--vp9-opts` | No default. | `--vp9-opts '{"row-mt":1,"deadline":"good","cpu-used":2}'` | Specify options to tweak VP9 encoding speed. `row-mt`, `deadline`, and `cpu-used` are the only values supported at the moment. This can only be set with the command line or JSON configuration file. It is not configurable with the Web UI. |

### File Name Formatting
Enable this feature with `--filename-times`. You can edit the name of your video file if you need to trim it to a specific section. Here are a few examples.

1) `000020.mp4`
    - This trims and compresses the video from 00:00:20 to the end of the clip.
2) `000020-000145.mp4`
    - This trims and compresses the video from 00:00:20 to 00:01:45.
3) `SomethingElse.mp4`
    - Compresses the entire video if the first six characters of the file's name aren't numeric.

### JSON Configuration
If your encoding job will always be the same, you can reference a JSON configuration file instead of passing a long list of arguments to the command line.

```
{
    "target_filesize": 8.0,
    "audio_br": 96,
    "crop": "",
    "output": "",
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
  - `"times": {}` -> if you do not wish to trim the start and stop time of the file.
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
    -o D:/shadowplay/ \
    --filename-times
```

The example above takes a 5120x1440 resolution video as its input. The script trims the video from 00:00:50 to 00:01:45 (specified in the [file name](#file-name-formatting), and enabled with `--filename-times`). It crops a 2560x1440 section starting at 1280 pixels from the top-left and 0 pixels down (`-x`). The output file will be located in `D:/shadowplay/` (`-o`) with a new resolution of 1920x1080 (`-r`), and it will be 50MB (`-s`). The audio bitrate will be reduced to 48k (`-a`) as well, but that's probably going to sound terrible.

![](https://github.com/zfleeman/ffmpeg4discord/assets/1808564/ac0663ee-64df-4b22-a1c3-4a8556c2eb78)

## Web UI

The web UI can be activated by adding `--web` to your `ff4d` call.

```
ff4d cool_clip.mp4 -r 1280x720 -s 20 --web
```

That command will spin up a Flask server on your local machine and launch a rendered webpage with the video as the centerpiece. The flags you provide to `ff4d` will fill in the defaults for the form. You can override/replace the values with the web form.

You can drag the video playhead to different portions of the video and click the "Set Start/End Time" buttons to specify the section of the video you want to be clipped out. You can also use the range sliders underneath the buttons if you prefer. A "Preview Selection" button is provided for your convenience, and it does what it sounds like.

https://github.com/zfleeman/ffmpeg4discord/assets/1808564/ff323bcb-4747-437b-808f-ce48b8c269ce

Note that the Flask server doesn't automatically shut down, so you'll need to manually terminate it by closing the terminal window where it's running.

## Sample Batch File

To enable "drag and drop" functionality for this package, Windows users can create a `.bat` file with the following code snippet. Once the file is created, you can drag and drop any `.mp4` file on top of it, and it will run with the flags specified in the "[Optional Flags](#optional-flags)" section. This example is a Batch file that will launch the web UI.

```batch
@echo off
Set filename=%1
ff4d %filename% -o "C:/output/folder/" --web
PAUSE
```

## Thanks!

Yes, this is a simple collection of Python files using FFmpeg tricks that is masquerading as a robust Audio/Video tool. But! I use this nearly every day to quickly share videos with people on various messaging apps that have built-in video players. I don't have to share a link that embeds a video player this way, and I guess that's important to me?

I like working on this! Enjoy!
