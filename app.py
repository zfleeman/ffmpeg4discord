import os
from utils.arguments import get_args
from twopass.twopass import TwoPass

# if __name__ == "main":

args = get_args()
twopass = TwoPass(**args)

run = True

while run:
    end_fs = twopass.filesize * 8192
    br = twopass.get_bitrate(filesize=end_fs)

    pass_one_params = {
        "pass": 1,
        "f": "null",
        "vsync": "cfr",
        "c:v": "libx264",
    }
    pass_one_params.update(**br)

    pass_two_params = {
        "pass": 2,
        "c:v": "libx264",
        "c:a": "aac",
        "b:a": twopass.audio_br * 1000,
    }
    pass_two_params.update(**br)

    print("Performing first pass.")
    twopass.first_pass(params=pass_one_params)
    print("First pass complete.\n")

    print("Performing second pass.")
    twopass.second_pass(params=pass_two_params)
    print("Second pass complete.\n")

    output_fs = os.path.getsize(twopass.output_filename) * 0.00000095367432
    run = twopass.target_fs <= output_fs
    output_fs = round(output_fs, 2)

    if run:
        print(f"Output file size ({output_fs}MB) still above the target of {twopass.target_fs}MB.\nRestarting...\n")
        os.remove(twopass.output_filename)
        twopass.filesize -= 0.2
    else:
        print(f"\nSUCCESS!!\nThe smaller file ({output_fs}MB) is located at {twopass.output_filename}")
