import os
from utils.arguments import get_args
from twopass import TwoPass

args = get_args()
twopass = TwoPass(**args)
end_fs = args["target_filesize"]

run = True

while run:
    twopass.run()

    output_fs = os.path.getsize(twopass.output_filename) * 0.00000095367432
    run = end_fs <= output_fs
    output_fs = round(output_fs, 2)

    if run:
        print(f"Output file size ({output_fs}MB) still above the target of {end_fs}MB.\nRestarting...\n")
        os.remove(twopass.output_filename)
        twopass.target_filesize -= 0.2
    else:
        print(f"\nSUCCESS!!\nThe smaller file ({output_fs}MB) is located at {twopass.output_filename}")
