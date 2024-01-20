@echo off
Set filename=%1
python "C:/path/to/ffmpeg4discord.py" %filename% -o "C:/output/folder/"
DEL "ffmpeg2*"
PAUSE