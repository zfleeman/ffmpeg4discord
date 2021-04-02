FROM python:3-alpine
RUN apk add  --no-cache ffmpeg
WORKDIR /usr/app/
COPY discord.py .
RUN mkdir -p /usr/app/in/
RUN mkdir -p /usr/app/out/
ENV codec=vp9
ENV audio_br=96
ENV fs=8.0
ENV reso=1280x720
CMD ["python","/usr/app/discord.py"]