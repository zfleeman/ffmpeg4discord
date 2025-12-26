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

> **NOTE:** This package relies on the external FFmpeg binary, and updates to FFmpeg may cause unexpected errors; please raise an issue if you encounter any problems.

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

> **Boolean flags** support both `--flag` and `--no-flag` forms (e.g. `--web` / `--no-web`).

| Flag | Default | Example | Description |
|---|---|---|---|
| `-o`<br>`--output` | current working directory | `-o "C:/Users/zflee/A Folder"`<br>`-o "C:/Users/zflee/Desktop/A Folder/filename.mp4"` | Output directory **or** full output filename. If you provide a directory, `ff4d` will generate a timestamped filename. If you provide a filename, `ff4d` will use it (and will correct the extension if it doesn’t match the selected codec). |
| `-s`<br>`--target-filesize` | 10 | `-s 50` | Target output file size in MiB. The encoder will iterate until it gets under this size (unless `--approx` is used). |
| `-a`<br>`--audio-br` | 96 | `-a 128` | Audio bitrate in kbps. Lowering this allows a slightly higher video bitrate for the same target file size. |
| `-c`<br>`--codec` | x264 | `-c hevc_nvenc` | Video "codec profile". These aren't 1:1 titles with the FFmpeg codec choices, because modern codecs require more tweaking for encoding performance, so I've setup a profile for `vp9` and `av1` speed. Options are ordered from "most compatible" to "least compatible": `x264`, `h264_nvenc`, `x265`, `hevc_nvenc`, `vp9`, `av1`. See [Notes on Codec Selection](#notes-on-codec-selection) for more information. |
| `-r`<br>`--resolution` | off | `-r 1280x720` | Scale the output video to a specific resolution (format: `WIDTHxHEIGHT`). |
| `-x`<br>`--crop` | No default | `-x 255x0x1410x1080` | Crop the input before encoding (format: `x_offsetx y_offsetx widthx height`). See [FFmpeg crop documentation](https://ffmpeg.org/ffmpeg-filters.html#Examples-61). |
| `-f`<br>`--framerate` | off | `-f 30` | Output frame rate (FPS). If you specify a value higher than the input video’s FPS, the original FPS will be kept. |
| `--from` | No default | `--from 00:01:00` | Start time for trimming the input (timestamp format `HH:MM:SS`). |
| `--to` | No default | `--to 00:01:20` | End time for trimming the input (timestamp format `HH:MM:SS`). |
| `--filename-times` | false | `--filename-times` | Parse From/To timestamps from the input filename. See [File Name Formatting](#file-name-formatting). |
| `--approx` | false | `--approx` | Approximate the target size: do a single 2-pass encode and **do not** loop to get under the target. |
| `-an`<br>`--no-audio` | false | `-an` | Do not include any audio stream in the output. (Overrides `--amix` / `--astreams`.) To explicitly re-enable audio after setting this in a config, use `--no-no-audio`. |
| `--amix` | false | `--amix` | Mix all (selected) audio streams into one output track. When off, only the default/first audio track is used. |
| `--amix-normalize` | false | `--amix-normalize` | When mixing audio, normalize volume levels. Specifying this implies `--amix`. |
| `--astreams` | all | `--astreams "0,1"` | Comma-separated list of **0-based audio stream positions** to include. When used with `--amix`, those streams will be mixed; otherwise, only the first selected stream is kept. |
| `-v`<br>`--verbose` | false | `--verbose` | Enable verbose FFmpeg logging (useful for debugging). |
| `--config` | off | `--config config.json` | Path to a JSON file containing a saved configuration. When a setting is provided by both JSON and CLI flags, the CLI flag wins. See [JSON Configuration](#json-configuration). |
| `--web` | false | `--web` | Launch the Web UI for this job. See [Web UI](#web-ui). |
| `-p`<br>`--port` | random (when `--web`) | `-p 5333` | Run the Web UI on a specific port. If omitted, a random free port between 5000–6000 is chosen. |

### File Name Formatting

Enable this feature with `--filename-times`. You can edit the name of your video file if you need to trim it to a specific section. Here are a few examples.

1) `000020.mp4`
    - This trims and compresses the video from 00:00:20 to the end of the clip.
2) `000020-000145.mp4`
    - This trims and compresses the video from 00:00:20 to 00:01:45.
3) `SomethingElse.mp4`
    - Compresses the entire video if the first six characters of the file's name aren't numeric.

### JSON Configuration

If your encoding job uses the same settings consistently, you can simplify your workflow by referencing a JSON configuration file instead of specifying multiple command-line arguments. This feature was designed for advanced users or "workflow people."

When using both a JSON configuration file and command-line flags, the **command-line flag values take precedence** over the values defined in the JSON. For example, if `"target_filesize"` is specified in the JSON file and you include the `--target-filesize` (or `-s`) flag in your command, the command-line value will be used.

If you supply a configuration JSON file, include only the settings that differ from the [default values](#optional-flags). Any omitted values will automatically use their defaults.

#### Example JSON File Configuration

Create a new plain text JSON file (`my-config.json`) structured like this:

```json
{
    "target_filesize": 10.0,
    "resolution": "1280x720",
    "codec": "libvpx-vp9",
    "to": "00:00:40"
}
```

And then you would call `ff4d` like this:

```bash
ff4d my-video.mp4 --config my-config.json
```

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

## Notes on Codec Selection

Different codecs have different trade-offs in terms of quality, speed, file size, and compatibility. “Compatibility” here refers to how widely a format can be played across devices, browsers, operating systems, and media players without requiring special software or recent hardware.

- **`x264` (H.264, CPU)**
  General‑purpose default. Produces H.264 video that is widely supported across virtually all modern devices, browsers, and players. Good balance of quality, speed, and compatibility.
  [FFmpeg trac link](https://trac.ffmpeg.org/wiki/Encode/H.264)

- **`h264_nvenc` (H.264, NVENC GPU)**
  Hardware‑accelerated H.264 using an NVIDIA GPU. Typically faster than `x264` with slightly lower quality at the same bitrate. Compatibility of the output files is essentially the same as `x264`; the difference is how the video is encoded, not how it is played.
  [FFmpeg trac link](https://trac.ffmpeg.org/wiki/HWAccelIntro#NVENC)

- **`x265` (HEVC, CPU)**
  HEVC encoder that can provide approximately 25–50% lower bitrate than H.264 (`x264`) at comparable visual quality. Playback support is more limited than H.264: many newer devices and players support HEVC, but older hardware, some browsers, and certain embeds may not.
  [FFmpeg trac link](https://trac.ffmpeg.org/wiki/Encode/H.265)

- **`hevc_nvenc` (HEVC, NVENC GPU)**
  Hardware‑accelerated HEVC using an NVIDIA GPU. Similar compression benefits and compatibility characteristics as `x265`, but significantly faster encoding due to GPU offload.
  [FFmpeg trac link](https://trac.ffmpeg.org/wiki/HWAccelIntro#NVENC)

- **`vp9` (VP9, CPU, `.webm`)**
  Produces `.webm` video. VP9 can save about 20–50% bitrate compared to H.264 (`x264`) at similar quality. It is well supported in modern browsers (especially for web streaming) but may have more limited support in older devices, legacy players, and some hardware decoders.
  [FFmpeg trac link](https://trac.ffmpeg.org/wiki/Encode/VP9)

- **`av1` (AV1, CPU, `.mp4`/`.webm`/`.mkv`/others)**
  AV1 can offer around 30% better compression than VP9 and roughly 50% better than H.264 at comparable quality. However, playback support is still maturing: recent browsers and newer devices increasingly support AV1, but compatibility with older hardware, embedded players, and some software remains limited. Encoding is typically slower than the other options. I have had issues with using this codec to create shorter clips (< 15 seconds).
  [FFmpeg trac link](https://trac.ffmpeg.org/wiki/Encode/AV1)

## Thanks!

Yes, this is a simple collection of Python files using FFmpeg tricks that is masquerading as a robust Audio/Video tool. But! I use this nearly every day to quickly share videos with people on various messaging apps that have built-in video players. I don't have to share a link that embeds a video player this way, and I guess that's important to me?

I like working on this! Enjoy!
