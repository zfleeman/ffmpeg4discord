# Imports
import os
import sys
import math
import time

# Function for calculating the appropriate bitrate to use during conversion
def get_bitrate(duration, filesize, audio_br):
	br = math.floor(filesize/duration - audio_br)
	return br

def encode(ffmpeg_string, fname):
	os.system(ffmpeg_string)
	end_size = os.path.getsize("/usr/app/out/small_{fname}".format(fname = fname)) * 0.00000095367432
	if end_size < 8.0:
		print(ffmpeg_string.replace("\t","") + '\nThe FFMPEG string above has yielded a file whose size is ' + str(end_size) + 'MB.\nsmall_{fname} is ready for Discord.\n'.format(fname = fname))
		time.sleep(5)
		return False
	else:
		print(ffmpeg_string.replace("\t","") + '\nThe FFMPEG string above has yielded a file whose size is ' + str(end_size) + 'MB.\nsmall_{fname} is NOT ready for Discord, and will be re-run.\nMy bad.'.format(fname = fname))
		time.sleep(2)
		return True

run = True

fname = os.listdir("/usr/app/in/")[0]
fname_webm = fname.replace(".mp4",".webm")
os.rename("/usr/app/in/" + fname, "/usr/app/in/" + fname.replace(" ", ""))
fname = fname.replace(" ", "")
startstring = fname[0:2] + ':' + fname[2:4] + ':' + fname[4:6]
endstring = fname[7:9] + ':' + fname[9:11] + ':' + fname[11:13]

try:
	int(fname[0:6])
	timestamp_run = True
	startseconds = int(fname[0:2])*60*60 + int(fname[2:4])*60 + int(fname[4:6])
	try:
		int(fname[11:13])
		endseconds = int(fname[7:9])*60*60 + int(fname[9:11])*60 + int(fname[11:13])
	except:
		pass
except:
	timestamp_run = False

# ffprobe to calculate the total duration of the clip.
duration = math.floor(float(os.popen("ffprobe -v error -show_entries format=duration -of default=noprint_wrappers=1:nokey=1 /usr/app/in/{fname}".format(fname = fname)).read()))

# Filesize for Discord.
fs = 8.0

# Audio bitrate of the converted clip.
audio_br = 96

while run:
	# Conversion to KiB
	discord_fs = fs * 8000

	if timestamp_run:

		if len(fname) < 11:
			br = get_bitrate(duration = duration - startseconds, filesize = discord_fs, audio_br = audio_br)
			ffmpeg_string = '''
				ffmpeg -y -i /usr/app/in/{fname} -g 48 -keyint_min 48 -sc_threshold 0 -threads 8 -speed 4 -row-mt 1 -vsync cfr -ss {startstring} -c:v libvpx-vp9 -b:v {br}k -an -pass 1 -f webm /dev/null && ffmpeg -i /usr/app/in/{fname} -ss {startstring} -keyint_min 48 -sc_threshold 0 -row-mt 1 -threads 8 -speed 2 -tile-columns 4 -c:v libvpx-vp9 -b:v {br}k -pass 2 -c:a libopus -b:a 96k -s 1280x720 "/usr/app/out/small_{fname_webm}" -y
			'''.format(fname = fname, startstring = startstring, br = br, fname_webm = fname_webm)

		else:
			br = get_bitrate(duration = endseconds - startseconds, filesize = discord_fs, audio_br = audio_br)
			ffmpeg_string = '''
				ffmpeg -y -i /usr/app/in/{fname} -g 48 -keyint_min 48 -sc_threshold 0 -threads 8 -speed 4 -row-mt 1 -vsync cfr -ss {startstring} -to {endstring} -c:v libvpx-vp9 -b:v {br}k -an -pass 1 -tile-columns 4 -f webm /dev/null && ffmpeg -i /usr/app/in/{fname} -ss {startstring} -to {endstring} -keyint_min 48 -sc_threshold 0 -row-mt 1 -threads 8 -speed 2 -tile-columns 4 -c:v libvpx-vp9 -b:v {br}k -pass 2 -c:a libopus -b:a 96k -s 1280x720 "/usr/app/out/small_{fname_webm}" -y
			'''.format(fname = fname, startstring = startstring, endstring = endstring, br = br, fname_webm = fname_webm)

	else:
		br = get_bitrate(duration = duration, filesize = discord_fs, audio_br = audio_br)
		ffmpeg_string = '''
			ffmpeg -y -i /usr/app/in/{fname} -g 48 -keyint_min 48 -sc_threshold 0 -threads 8 -speed 4 -row-mt 1 -c:v libvpx-vp9 -b:v {br}k -an -pass 1 -f webm /dev/null && ffmpeg -i /usr/app/in/{fname} -keyint_min 48 -sc_threshold 0 -row-mt 1 -threads 8 -speed 2 -tile-columns 4 -c:v libvpx-vp9 -b:v {br}k -pass 2 -c:a libopus -b:a 96k -s 1280x720 "/usr/app/out/small_{fname_webm}" -y
		'''.format(fname = fname, br = br, fname_webm = fname_webm)

	run = encode(ffmpeg_string, fname = fname_webm)
	
	if run:
		fs = fs - 0.2