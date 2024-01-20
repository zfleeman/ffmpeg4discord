FROM python:3-alpine
RUN apk add --no-cache ffmpeg
RUN pip install ffmpeg-python
RUN mkdir -p /usr/app/out/
WORKDIR /usr/app/
COPY ffmpeg4discord.py .
ENTRYPOINT ["python", "-u", "ffmpeg4discord.py", "-o", "/usr/app/out/"]