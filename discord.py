# Imports
import os
import math

# Function for calculating the appropriate bitrate to use during conversion
def get_bitrate(duration, filesize, audio_br):
	br = math.floor(filesize/duration - audio_br)
	return br, br * 0.50, br * 1.45

def encode(ffmpeg_string, output_name):
	os.system(ffmpeg_string)
	end_size = os.path.getsize("/usr/app/out/{output_name}".format(output_name = output_name)) * 0.00000095367432
	if end_size < 8.0:
		print(ffmpeg_string.replace("\t","") + '\nThe FFMPEG string above has yielded a file whose size is ' + str(end_size) + 'MB.\n{output_name} is ready for Discord.\n'.format(output_name = output_name))
		return False
	else:
		print(ffmpeg_string.replace("\t","") + '\nThe FFMPEG string above has yielded a file whose size is ' + str(end_size) + 'MB.\n{output_name} is NOT ready for Discord, and will be re-run.\nMy bad.'.format(output_name = output_name))
		return True

def time_calculations(fname, length):
	startstring = fname[0:2] + ':' + fname[2:4] + ':' + fname[4:6]
	endstring = fname[7:9] + ':' + fname[9:11] + ':' + fname[11:13]

	try:
		int(fname[0:6])
		startseconds = int(fname[0:2])*60*60 + int(fname[2:4])*60 + int(fname[4:6])
		try:
			int(fname[11:13])
			endseconds = int(fname[7:9])*60*60 + int(fname[9:11])*60 + int(fname[11:13])
			duration = endseconds - startseconds
			timestamped_section = f'-ss {startstring} -to {endstring}'
		except:
			duration = length - startseconds
			timestamped_section = f'-ss {startstring}'
	except:
		duration = length
		timestamped_section = ''

	return duration, timestamped_section

fname = os.listdir("/usr/app/in/")[0]
os.rename("/usr/app/in/" + fname, "/usr/app/in/" + fname.replace(" ", ""))
fname = fname.replace(" ", "")

# ffprobe to calculate the total duration of the clip.
length = math.floor(float(os.popen("ffprobe -v error -show_entries format=duration -of default=noprint_wrappers=1:nokey=1 /usr/app/in/{fname}".format(fname = fname)).read()))
# Filesize for Discord.
fs = 8.0
# Audio bitrate of the converted clip.
audio_br = 96

duration, timestamped_section = time_calculations(fname, length)

run = True

codecs = {
	'vp9':{
		'pass1':'-vf scale=1280x720 -g 240 -threads 8 -speed 4 -row-mt 1 -tile-columns 2 -vsync cfr -c:v libvpx-vp9	-pass 1  -an',
		'pass2':'-vf scale=1280x720 -g 240 -threads 8 -speed 2 -row-mt 1 -tile-columns 2 -c:v libvpx-vp9 -c:a libopus -pass 2',
		'output_name':'small_' + fname.replace(".mp4",".webm")
	},
	'x264':{
		'pass1':'-vf scale=854x480 -vsync cfr -c:v libx264 -pass 1 -an',
		'pass2':'-vf scale=854x480 -c:v libx264 -c:a aac -pass 2 ',
		'output_name':'small_' + fname
	},
	'x265':{
		'pass1':'-vf scale=1280x720 -c:v libx265 -vsync cfr -x265-params pass=1 -an',
		'pass2':'-vf scale=1280x720 -c:v libx265 -x265-params pass=2 -c:a aac',
		'output_name':'small_' + fname
	}
}

codec = os.getenv('codec')

while run:
	# Conversion to KiB
	discord_fs = fs * 8192
	br, minbr, maxbr = get_bitrate(duration = duration, filesize = discord_fs, audio_br = audio_br)
	ffmpeg_string = f'''
		ffmpeg -y -i /usr/app/in/{fname} {timestamped_section} \
			{codecs[codec]['pass1']} \
			-b:v {br}k -minrate {minbr}k -maxrate {maxbr}k \
			-f null /dev/null && \
		ffmpeg -i /usr/app/in/{fname} {timestamped_section} \
			{codecs[codec]['pass2']} \
			-b:a {audio_br}k -b:v {br}k -minrate {minbr}k -maxrate {maxbr}k \
			"/usr/app/out/{codecs[codec]['output_name']}" -y
	'''

	run = encode(ffmpeg_string, output_name = codecs[codec]['output_name'])
	
	if run:
		fs = fs - 0.2