FROM python:3-alpine
RUN apk add  --no-cache ffmpeg
WORKDIR /usr/app/
COPY discord.py .
RUN mkdir -p /usr/app/in/
RUN mkdir -p /usr/app/out/
CMD ["python","/usr/app/discord.py"]