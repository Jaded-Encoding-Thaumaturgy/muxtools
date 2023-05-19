from vodesautomatisierung import *
from pprint import pprint

# wowzers = sanitize_trims([(None, -24)], 30)

# print(has_libFLAC())
# print(has_libFDK())

# FDK_AAC().encode_audio(AudioFile("text.mp4"))


# trims = [(570, None), (59, 346), (1240, None), (None, 372), (None, 24)]
# print(sanitize_trims(trims, 2000))

# trims = [(59, 346), (1240, -34), (None, 372), (None, 24)]
# print(sanitize_trims(trims, 2000))

# This file was made by taking a legitimate 24, truncating to 16 and setting back up to 24
# I don't have a real world example on this PC :(
ext = FFMpeg.Extractor().extract_audio("fake24.mka")

ff_lossless = FFMpeg.Trimmer([(24, 3000), (5000, 6000)]).trim_audio(ext)
sox = Sox([(24, 3000), (5000, 6000)]).trim_audio(ext)

lossy = Opus().encode_audio(ext)
ff_lossy = FFMpeg.Trimmer((24, 1337)).trim_audio(lossy)  # Supports multiple trims too but not a great idea
print(ff_lossy.to_mka())  # This, in theory, creates an mka with the delay applied

