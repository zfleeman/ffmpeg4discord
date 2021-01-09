Set filename=%1
For %%A in ("%filename%") do (
    Set Folder=%%~dpA
    Set Name=%%~nxA
)
docker run --rm -v %1:/usr/app/in/%Name% -v D:\shadowplay:/usr/app/out/ zachfleeman/ffmpeg4discord
PAUSE