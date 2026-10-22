"""
This module provides the main entry point for the ffmpeg4discord application.

It supports both command-line and web-based interfaces for performing two-pass
video encoding using FFmpeg. The script allows users to specify various encoding
parameters and target file sizes, and it will iteratively adjust the encoding
settings to meet the desired output file size.

Functions:
- twopass_loop: Executes the two-pass encoding process in a loop until the target file size is achieved.
- open_browser: Opens the default web browser to the specified port.
- format_commands: Lists the ffmpeg commands for an encode with a short explanation.
- success_message: The message shown when an encode finishes.
- source_facts: Facts about the input video that the web page checks the form against.
- form_values: The values the web UI's form shows.
- parse_encode_form: Checks the web UI's form and turns it into EncodeSettings.
- main: The main function that parses command-line arguments and starts the encoding process or web server.
"""

import atexit
import logging
import math
import re
import shutil
import threading
import time
import webbrowser
from dataclasses import dataclass, field, replace
from pathlib import Path
from textwrap import dedent
from typing import Callable, Optional

from flask import Flask, redirect, render_template, request, send_file, url_for

from ffmpeg4discord import arguments
from ffmpeg4discord.twopass import EncodeResult, EncodeSettings, TwoPass, available_codecs
from ffmpeg4discord.versioning import check_for_update

# smallest fraction the target size is cut by on each retry
MIN_RETRY_STEP = 0.02

# the formats the web UI accepts, e.g. 1280x720 and 255x0x1410x1080
RESOLUTION_PATTERN = re.compile(r"\d+x\d+")
CROP_PATTERN = re.compile(r"\d+x\d+x\d+x\d+")


def twopass_loop(
    twopass: TwoPass,
    settings: EncodeSettings,
    approx: bool = False,
    on_pass: Optional[Callable[[str, Path], None]] = None,
) -> EncodeResult:
    """
    Encodes with `settings`, then re-encodes at a lower bitrate until the output is under the target size.

    Args:
        twopass (TwoPass): The TwoPass for the input video.
        settings (EncodeSettings): What to encode. Its `target_filesize` is the size to get under.
        approx (bool): Keep the first encode, even if it's over the target.
        on_pass: Passed to `TwoPass.run()`, which calls it before each pass with a file ffmpeg writes progress to.

    Returns:
        The last encode's result.
    """
    target_filesize = settings.target_filesize

    while True:
        result = twopass.run(settings, on_pass=on_pass)

        # check if the filesize is within the target
        if result.output_filesize < target_filesize or approx:
            break

        print(
            dedent(
                f"""\033[31m
                The output file size ({round(result.output_filesize, 2)}MB) is still above the target of {target_filesize}MB.
                Restarting...
                \033[0m"""
            )
        )
        Path(result.output_filename).unlink()

        # lower the target size for the next run, which lowers the bitrate.
        # scale by how far off we are, but always cut by at least MIN_RETRY_STEP so an output
        # that lands just over the target doesn't retry at a near-identical bitrate
        adjustment_ratio = min(target_filesize / result.output_filesize, 1 - MIN_RETRY_STEP)
        settings = replace(settings, target_filesize=max(settings.target_filesize * adjustment_ratio, 0.1))

    return result


def open_browser(port: int) -> None:
    """
    Opens the default web browser to the specified port.

    Args:
        port (int): The port number to open in the web browser.
    """
    time.sleep(0.5)
    webbrowser.open(f"http://127.0.0.1:{port}")


def format_commands(commands: list[str]) -> str:
    """
    Lists the ffmpeg commands for an encode, so users can see what ff4d did on their behalf.

    Args:
        commands (list[str]): The commands from `EncodeResult.commands`.
    """
    if len(commands) == 1:
        header = "Here's what this encode looks like as a plain FFmpeg command:"
    else:
        header = "Here's what this encode looks like as plain FFmpeg commands (a two-pass encode runs FFmpeg twice):"
    return "\n\n".join([header, *commands])


def success_message(result: EncodeResult) -> str:
    """The message shown when an encode finishes."""
    output_path = Path(result.output_filename).resolve()
    return f"Your compressed video file ({round(result.output_filesize, 2)}MB) is located at {output_path}"


# What the web UI's progress line calls each pass
PASS_LABELS = {"first": "First pass", "second": "Second pass", "single": "Encoding"}


def progress_seconds(progress_file: Optional[Path]) -> Optional[float]:
    """How many seconds of video ffmpeg's -progress file says it has encoded, or None if it hasn't reported a time."""
    if progress_file is None:
        return None
    try:
        text = progress_file.read_text()
    except OSError:
        return None
    # ffmpeg adds a block of key=value lines about twice a second, so the last time is the newest.
    # Older builds call it out_time_ms, but it's in microseconds there too. It's N/A until video comes out.
    times = re.findall(r"^out_time_(?:us|ms)=(\d+)", text, re.MULTILINE)
    return int(times[-1]) / 1_000_000 if times else None


@dataclass
class EncodeJob:
    """
    A web UI encode. It runs in a background thread while the page polls /status for its progress.

    Attributes:
        values (dict): The submitted form, to show again while and after the encode runs.
        clip_seconds (float): The trimmed clip's length, for working out the progress.
        codec (str): The encode's codec, e.g. "vp9".
        state (str): "running", then "done" or "failed".
        attempt (int): Which attempt is running. ff4d tries again when an output is over the target.
        pass_name (str): The running pass: "first", "second", or "single" for hardware encoders.
        progress_file (Path): The file ffmpeg writes the running pass's progress to.
        pass_started (float): When the running pass started, from time.monotonic().
        result (EncodeResult): The finished encode, once the state is "done".
        errors (list[str]): What went wrong, once the state is "failed".
    """

    values: dict
    clip_seconds: float
    codec: str = ""
    state: str = "running"
    attempt: int = 0
    pass_name: str = ""
    progress_file: Optional[Path] = None
    pass_started: float = 0.0
    result: Optional[EncodeResult] = None
    errors: list[str] = field(default_factory=list)

    def run(self, twopass: TwoPass, settings: EncodeSettings, approx: bool) -> None:
        """Runs the encode and its retries. It records errors instead of raising, since nobody would catch them."""
        try:
            self.result = twopass_loop(twopass, settings, approx, on_pass=self.start_pass)
            self.state = "done"
        except ValueError as exc:
            # TwoPass raises ValueError for settings that can't work, e.g. no bitrate left for video on a retry
            self.errors = [str(exc)]
            self.state = "failed"
        except RuntimeError as exc:
            # FFmpeg failed. Its own message and the full command are only useful in the terminal.
            logging.error(exc)
            self.errors = ["FFmpeg failed while encoding. Its error message is in the terminal running ff4d."]
            self.state = "failed"
        except Exception:
            # Anything else would leave the job "running" forever and block every later encode
            logging.exception("The encode failed")
            self.errors = ["Something went wrong while encoding. The details are in the terminal running ff4d."]
            self.state = "failed"

    def start_pass(self, pass_name: str, progress_file: Path) -> None:
        """TwoPass.run() calls this before each pass. A first or single pass means a new attempt has started."""
        if pass_name in ("first", "single"):
            self.attempt += 1
        self.progress_file = progress_file
        self.pass_started = time.monotonic()
        self.pass_name = pass_name

    def remove_temp_folder(self) -> None:
        """
        Deletes a running encode's temp folder. The encode thread is a daemon, so when Ctrl+C stops the server,
        the TemporaryDirectory in TwoPass.run() never gets to clean up after itself.
        """
        if self.state != "running" or self.progress_file is None:
            return
        folder = self.progress_file.parent
        # ffmpeg stops on Ctrl+C too, but Windows won't delete a file it still has open, so give it a moment to exit
        for _ in range(10):
            shutil.rmtree(folder, ignore_errors=True)
            if not folder.exists():
                return
            time.sleep(0.2)
        logging.warning(f"Couldn't delete the encode's temp folder: {folder}")

    def status(self) -> dict:
        """What /status sends the page. While running, `percent` covers the whole encode and `label` describes it."""
        if self.state != "running":
            return {"state": self.state}
        if not self.pass_name:
            return {"state": "running", "percent": 0, "label": "Starting…"}

        # Each pass of a two-pass encode gets half of the bar
        start, share = {"first": (0, 50), "second": (50, 50), "single": (0, 100)}[self.pass_name]
        seconds = progress_seconds(self.progress_file)
        if seconds is None:
            # No time yet. Most passes report one within a second, but VP9's first pass writes no video, so it never does.
            done = 0
            label = f"{PASS_LABELS[self.pass_name]}: running for {time.monotonic() - self.pass_started:.0f} s"
            if self.codec == "vp9" and self.pass_name == "first":
                label += ". VP9 doesn't report progress until this pass ends."
        else:
            done = min(seconds / self.clip_seconds, 1)
            label = f"{PASS_LABELS[self.pass_name]}: {done:.0%}"
        if self.attempt > 1:
            label = f"Attempt {self.attempt}, since the last one was over the target. {label}"
        return {"state": "running", "percent": round(start + share * done, 1), "label": label}


def source_facts(twopass: TwoPass) -> dict:
    """Facts about the input video that the web page's JavaScript checks the form against."""
    stream = twopass.video_stream or {}
    width, height = stream.get("width"), stream.get("height")
    # Phones often store video sideways with a rotation tag, and ffmpeg's filters see the rotated size.
    rotation = int(stream.get("tags", {}).get("rotate", 0))
    for data in stream.get("side_data_list", []):
        rotation = int(data.get("rotation", rotation))
    if rotation % 180 == 90:
        width, height = height, width

    return {
        "duration": twopass.duration,
        "width": width,
        "height": height,
        "framerate": twopass.init_framerate,
        "size_mib": twopass.input_filesize,
        "audio_tracks": len(twopass.audio_streams),
        "audio_kbps": twopass.source_audio_br / 1000 if twopass.source_audio_br else None,
    }


def form_values(twopass: TwoPass, settings: EncodeSettings, approx: bool, form=None) -> dict:
    """
    The values the web UI's form shows. They come from `settings`, or from `form` when the page is shown again
    after a bad submit, so the user keeps what they typed.

    Args:
        twopass (TwoPass): The TwoPass for the input video.
        settings (EncodeSettings): The settings that fill the form.
        approx (bool): Whether the "Approximate file size" switch is on.
        form: The submitted form (Flask's `request.form`), if any.
    """
    if settings.amix:
        amix_mode = "mix_normalize" if settings.amix_normalize else "mix"
    else:
        amix_mode = "off"

    start, end = twopass.clip_times(settings)
    source_kbps = twopass.source_audio_br / 1000 if twopass.source_audio_br else ""
    values = {
        "startTime": start,
        "endTime": end,
        "target_filesize": settings.target_filesize,
        "approx": approx,
        "resolution": settings.resolution,
        "crop": settings.crop,
        "output": settings.output.resolve(),
        "codec": settings.codec,
        "framerate": settings.framerate or "",
        "audio_br": settings.audio_br or source_kbps,
        "include_audio": not settings.no_audio,
        "amix_mode": amix_mode,
        "astreams": settings.astreams,  # None means every track is checked
        "verbose": settings.verbose,
    }
    if form is None:
        return values

    text_fields = [
        "startTime",
        "endTime",
        "target_filesize",
        "resolution",
        "crop",
        "output",
        "codec",
        "framerate",
        "audio_br",
    ]
    for name in text_fields:
        values[name] = form.get(name, "")
    for name in ["approx", "include_audio", "verbose"]:
        values[name] = name in form
    # The page disables the audio options when audio is off, so they're only in the form when it's on.
    if values["include_audio"]:
        values["amix_mode"] = form.get("amix_mode", "off")
        values["astreams"] = [int(i) for i in form.getlist("astreams") if i.isdecimal()]
    return values


def _number(text, convert=float):
    """Converts form text to a number. Returns None if it's blank, missing, or not a number."""
    try:
        value = convert(text.strip())
    except (AttributeError, ValueError):
        return None
    # float() accepts "nan" and "inf", which aren't useful settings
    return value if math.isfinite(value) else None


def parse_encode_form(form, twopass: TwoPass, codecs: list[str]) -> tuple[EncodeSettings | None, list[str]]:
    """
    Checks the web UI's form and turns it into EncodeSettings.

    Args:
        form: The submitted form (Flask's `request.form`).
        twopass (TwoPass): The TwoPass for the input video, used for its duration, size, and audio tracks.
        codecs (list[str]): The codecs this computer can use.

    Returns:
        The settings and an empty list, or None and a list of error messages for the user.
    """
    errors = []

    start = _number(form.get("startTime"))
    end = _number(form.get("endTime"))
    if start is None or end is None:
        errors.append("The Start and End times must be numbers of seconds.")
    elif not 0 <= start < end <= twopass.duration:
        errors.append(
            f"The Start time must come before the End time, and both must be between 0 and {twopass.duration:g} seconds."
        )

    target = _number(form.get("target_filesize"))
    if target is None or target <= 0:
        errors.append("The File Size must be a number above 0.")
    elif target > twopass.input_filesize:
        errors.append(
            f"The File Size ({target:g} MiB) is larger than the input file ({twopass.input_filesize:.2f} MiB)."
        )

    codec = form.get("codec")
    if codec not in codecs:
        errors.append("Pick a Video Codec from the list.")

    resolution = form.get("resolution", "").strip()
    if resolution and not RESOLUTION_PATTERN.fullmatch(resolution):
        errors.append("The Resolution must be width x height, e.g. 1280x720, or left blank.")

    crop = form.get("crop", "").strip()
    if crop and not CROP_PATTERN.fullmatch(crop):
        errors.append(
            "The Crop must be four numbers joined by x (x offset, y offset, width, height), e.g. 255x0x1410x1080."
        )

    # Windows Explorer's "Copy as path" wraps the path in quotes
    output = Path(form.get("output", "").strip().strip('"'))
    if not output.is_dir() and not output.parent.is_dir():
        errors.append(f"The output folder {output.parent} doesn't exist.")

    # Frame rate and audio bitrate are optional, so only a filled-in field that isn't a valid number is an error.
    framerate = _number(form.get("framerate"), int)
    if form.get("framerate", "").strip() and (framerate is None or framerate <= 0):
        errors.append("The Frame Rate must be a whole number above 0, e.g. 30, or left blank to keep the original.")

    audio_kbps = _number(form.get("audio_br"))
    if form.get("audio_br", "").strip() and (audio_kbps is None or audio_kbps <= 0):
        errors.append("The Audio Bitrate must be a number above 0.")

    include_audio = "include_audio" in form
    astreams = [int(i) for i in form.getlist("astreams") if i.isdecimal()]
    # With more than one track the page shows a checkbox per track. Sending none would otherwise mean "all tracks".
    if include_audio and len(twopass.audio_streams) > 1 and not astreams:
        errors.append("Check at least one of the Audio Streams, or turn off Include Audio.")

    if errors:
        return None, errors

    amix_mode = form.get("amix_mode")
    settings = EncodeSettings(
        target_filesize=target,
        output=output,
        start=str(start),
        end=str(end),
        audio_br=audio_kbps,  # None (left blank) means the input's audio bitrate
        codec=codec,
        crop=crop,
        resolution=resolution,
        framerate=framerate,
        no_audio=not include_audio,
        amix=amix_mode in ("mix", "mix_normalize"),
        amix_normalize=amix_mode == "mix_normalize",
        astreams=astreams or None,
        verbose="verbose" in form,
    )
    return settings, []


def main() -> None:
    """
    The main function that parses command-line arguments and starts the encoding process or web server.
    """
    # Best-effort version check (never blocks startup)
    version_info = check_for_update(timeout_s=1.5)

    # CLI: show version + update notice early (for both CLI mode and web-launch mode)
    if version_info.current_version:
        print(f"ffmpeg4discord v{version_info.current_version}")
    else:
        print("ffmpeg4discord")

    if version_info.update_available:
        print(
            dedent(
                f"""\033[33m
                Update available: {version_info.latest_version} (you are running {version_info.current_version}).
                Upgrade with: pip install -U ffmpeg4discord
                \033[0m"""
            ).strip()
        )

    # get args from the command line
    args = arguments.get_args()
    web = args.pop("web")
    approx = args.pop("approx")
    dry_run = args.pop("dry_run")

    if web and dry_run:
        logging.warning("--dry-run is ignored with --web. Pick your settings in the browser instead.")

    if web:
        port = args.pop("port")

    path = Path(args.pop("filename")).resolve()
    args["output"] = Path(args["output"])
    # the rest of the args are the encode settings
    settings = EncodeSettings(**args)
    twopass = TwoPass(path)

    if web:
        # --from and --to fill in the form's starting trim, so check them before starting the server
        twopass.clip_times(settings)
        codecs = available_codecs()
        source = source_facts(twopass)
        # No static folder: serving the video's folder would expose every file next to it.
        app = Flask(__name__, static_folder=None)

        @app.route("/video")
        def video():
            return send_file(path)

        # The current or last encode. Only one runs at a time, and job_lock keeps two requests from both starting one.
        job = None
        job_lock = threading.Lock()

        @atexit.register
        def remove_temp_folder():
            if job is not None:
                job.remove_temp_folder()

        def render_page(values: dict, encoding: bool = False, **kwargs):
            return render_template(
                "web.html",
                file_url=url_for("video"),
                twopass=twopass,
                source=source,
                codecs=codecs,
                version_info=version_info,
                values=values,
                encoding=encoding,
                **kwargs,
            )

        @app.route("/")
        def index():
            # The page shows the current or last encode, so closing the tab and coming back loses nothing
            if job is None:
                return render_page(form_values(twopass, settings, approx), alert_hidden=True)
            if job.state == "running":
                return render_page(job.values, encoding=True, alert_hidden=True)
            if job.state == "failed":
                return render_page(job.values, alert_hidden=True, errors=job.errors)
            return render_page(
                job.values,
                message=success_message(job.result),
                commands_text=format_commands(job.result.commands),
            )

        @app.route("/status")
        def status():
            return job.status() if job else {"state": "idle"}

        @app.route("/encode", methods=["POST"])
        def form_twopass():
            nonlocal job
            with job_lock:
                if job is not None and job.state == "running":
                    values = form_values(twopass, settings, approx, request.form)
                    errors = ["An encode is already running. Wait for it to finish, then try again."]
                    return render_page(values, encoding=True, alert_hidden=True, errors=errors), 409

                # Each request builds its own settings, so nothing carries over from the last encode.
                form_settings, errors = parse_encode_form(request.form, twopass, codecs)
                # to loop or not to loop
                form_approx = "approx" in request.form
                if not errors:
                    try:
                        # A dry run raises for settings that can't work, like no bitrate left for video,
                        # so the user hears about it now instead of after the page starts showing progress.
                        twopass.run(form_settings, dry_run=True)
                    except ValueError as exc:
                        errors = [str(exc)]
                if errors:
                    values = form_values(twopass, settings, form_approx, request.form)
                    return render_page(values, alert_hidden=True, errors=errors), 400

                start, end = twopass.clip_times(form_settings)
                values = form_values(twopass, form_settings, form_approx)
                job = EncodeJob(values, clip_seconds=end - start, codec=form_settings.codec)
                worker = threading.Thread(
                    target=job.run, args=[twopass, form_settings, form_approx], name="Encode", daemon=True
                )
            worker.start()
            # Send the browser to the page that shows the progress. A refresh there doesn't submit the form again.
            return redirect(url_for("index"), code=303)

        threading.Thread(target=open_browser, args=[port], name="Open Browser").start()
        # Only this computer can reach the server. The form can write files anywhere, so keep it off the network.
        app.run("127.0.0.1", port=port)
    elif dry_run:
        result = twopass.run(settings, dry_run=True)
        print(format_commands(result.commands))
        if not approx:
            print("\nIf the output lands over the target size, ff4d re-encodes it at a lower bitrate.")
    else:
        result = twopass_loop(twopass, settings, approx)
        print(f"\n{format_commands(result.commands)}\n")
        print(success_message(result))


if __name__ == "__main__":
    main()
