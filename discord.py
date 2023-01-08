import ffmpeg
import argparse
import math
import os
from datetime import datetime

def get_bitrate(duration, filesize, audio_br):
    br = math.floor(filesize/duration - audio_br) * 1000
    return br, br * 0.50, br * 1.45

def time_calculations(fname, length):
    startstring = fname[0:2] + ':' + fname[2:4] + ':' + fname[4:6]
    endstring = fname[7:9] + ':' + fname[9:11] + ':' + fname[11:13]
    times = {}

    try:
        int(fname[0:6])
        startseconds = int(fname[0:2])*60*60 + int(fname[2:4])*60 + int(fname[4:6])
        times['ss'] = startstring
        try:
            int(fname[11:13])
            endseconds = int(fname[7:9])*60*60 + int(fname[9:11])*60 + int(fname[11:13])
            duration = endseconds - startseconds
            times['to'] = endstring
        except:
            duration = length - startseconds
    except:
        duration = length

    return duration, times

def apply_video_filters(ffInput):
    video = ffInput.video

    if args.crop:
        dim = args.crop.split('x')
        video = video.crop(x=dim[0], y=dim[1], width=dim[2], height=dim[3])
        args.inputratio = int(dim[2])/int(dim[3])
   
    if args.resolution:
        video = video.filter('scale', args.resolution)
        x = int(args.resolution.split('x')[0])
        y = int(args.resolution.split('x')[1])
        outputratio = x/y

        if args.inputratio != outputratio:
            print("!!!!!!!!!\n!WARNING!\n!!!!!!!!!")
            print("Your output resolution's aspect ratio does not match the\ninput resolution's or your croped resolution's aspect ratio.")
        
    return video

def first_pass(inputPath, params, times):
    ffInput = ffmpeg.input(inputPath, **times)
    video = apply_video_filters(ffInput)
    ffOutput = ffmpeg.output(video, 'pipe:', **params)
    ffOutput = ffOutput.global_args('-loglevel', 'quiet', '-stats')
    std_out, std_err = ffOutput.run(capture_stdout=True)

def second_pass(inputPath, outputPath, params, times):
    ffInput = ffmpeg.input(inputPath, **times)
    audio = ffInput.audio
    video = apply_video_filters(ffInput)
    ffOutput = ffmpeg.output(video, audio, outputPath, **params)
    ffOutput = ffOutput.global_args('-loglevel', 'quiet', '-stats')
    ffOutput.run(overwrite_output=True)

def get_new_fs(target_fs, output_filename):
    return target_fs <= os.path.getsize(output_filename) * 0.00000095367432

# args work
parser = argparse.ArgumentParser(prog='ffmpeg4discord', description='Video compression script.', epilog='Compress those sick clips, boi.')
parser.add_argument('filename', help='The full file path of the file that you wish to compress.')
parser.add_argument('-o', '--output', default='', help='The desired output directory where the file will land.')
parser.add_argument('-c', '--codec', choices=['libx264'], default='libx264', help='The codec that will be used during this conversion. libx264 is the most common and compatible codec.')
parser.add_argument('-s', '--filesize', default=8.0, type=float, help='The output file size in MB. Free Discord accepts a max of 8MB.')
parser.add_argument('-a', '--audio-br', default=96, type=float, help='Audio bitrate in kbps.')
# video filters
parser.add_argument('-x', '--crop', help="Cropping dimensions. Example: 255x0x1410x1080")
parser.add_argument('-r', '--resolution', help='The output resolution of your final video.')
args = parser.parse_args()

# pre-run variables
fname = args.filename.replace("\\", "/").split('/')[-1]
target_fs = args.filesize
probe = ffmpeg.probe(args.filename)
args.inputratio = probe['streams'][0]['width']/probe['streams'][0]['height']
duration = math.floor(float(probe['format']['duration']))
duration, times = time_calculations(fname, duration)
run = True

while run:
    end_fs = args.filesize * 8192
    br, minbr, maxbr = get_bitrate(duration=duration, filesize=end_fs, audio_br=args.audio_br)

    pass_one_params = {
        'pass': 1,
        'f': 'null',
        'vsync': 'cfr',
        'c:v': args.codec,
        'b:v': br,
        'minrate': minbr,
        'maxrate': maxbr,
        'bufsize': br * 2
    }

    pass_two_params = {
        'pass': 2,
        'c:v': args.codec,
        'c:a': 'aac',
        'b:a': args.audio_br * 1000,
        'b:v': br,
        'minrate': minbr,
        'maxrate': maxbr,
        'bufsize': br * 2
    }

    split_fname = fname.split('.')
    output_filename = args.output + 'small_' + \
        split_fname[0].replace(" ", "_") + datetime.strftime(datetime.now(), '_%Y%m%d%H%M%S.') + split_fname[1]

    print('Performing first pass.')
    first_pass(args.filename, pass_one_params, times)
    print('First pass complete.\n')

    print('Performing second pass.')
    second_pass(args.filename, output_filename, pass_two_params, times)
    print('Second pass complete.\n')

    run = get_new_fs(target_fs, output_filename)

    if run:
        print(f'Resultant file size still above the target of {target_fs}MB.\nRestarting.\n')
        os.remove(output_filename)
        args.filesize -= 0.2
    else:
        print(f'Smaller file located at {output_filename}')