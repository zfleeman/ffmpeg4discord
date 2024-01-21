import os
from utils.arguments import get_args
from twopass import TwoPass

# get args from the command line
args = get_args()

# instantiate the TwoPass class and save our target file size for comparison in the loop
twopass = TwoPass(**args)
end_fs = args["target_filesize"]

while twopass.run() >= end_fs:
    print(
        f"\nThe output file size ({round(twopass.output_filesize, 2)}MB) is still above the target of {end_fs}MB.\nRestarting...\n"
    )
    os.remove(twopass.output_filename)

    # adjust the class's target file size to set a lower bitrate for the next run
    twopass.target_filesize -= 0.2

print(f"\nSUCCESS!!\nThe smaller file ({round(twopass.output_filesize, 2)}MB) is located at {twopass.output_filename}")
