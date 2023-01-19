FROM python:3-alpine
RUN apk add --no-cache ffmpeg
RUN pip install ffmpeg-python
RUN mkdir -p /usr/app/out/
WORKDIR /usr/app/
COPY discord.py .
ENTRYPOINT ["python", "-u", "discord.py", "-o", "/usr/app/out/"]