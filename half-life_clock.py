#!/usr/bin/env python3
#
## Calomel.org Half-Life 1 (1998 series) talking clock
## Python port of half-life_clock.pl
#

import argparse
import subprocess
from datetime import datetime

BASE = "/home/mapenn/hlclock/wavs"
DEFAULT_VOLUME = 50   # matches hlclock.sh


def run_audio_command(command):
    """Stop with a useful diagnostic if an ALSA command fails."""
    try:
        subprocess.run(command, check=True)
    except subprocess.CalledProcessError as error:
        raise SystemExit(
            f"{command[0]} failed (exit status {error.returncode})"
        ) from None
    except OSError as error:
        raise SystemExit(f"Could not run {command[0]}: {error}") from None


parser = argparse.ArgumentParser(description="Half-Life 1 talking clock")
parser.add_argument(
    "-v", "--volume", type=int, default=DEFAULT_VOLUME,
    help=f"PCM volume percent, 0–100 (default: {DEFAULT_VOLUME}). "
         f"Use 80 for the old hlclock_high.sh behavior."
)
args = parser.parse_args()
if not 0 <= args.volume <= 100:
    parser.error("--volume must be between 0 and 100 (inclusive)")

## set PCM volume (was amixer -q -M sset PCM NN% in hlclock*.sh)
run_audio_command(["amixer", "-q", "-M", "sset", "PCM", f"{args.volume}%"])

## collect the system time
## 12 hour time
now = datetime.now()
hour = now.strftime("%I")   # zero-padded, e.g. "01".."12"
## 24 hour time
# hour = now.strftime("%H")

minute = int(now.strftime("%M"))
ampm = now.strftime("%p")   # "AM" / "PM"

audio = []

## "the time is" wav
audio.append(f"{BASE}/time_is.wav")

## the hour time wav
audio.append(f"{BASE}/{hour}.wav")

## the minute wav. check for minutes which are less than 20
## so numbers in the teens and 1-9 play
if minute > 20:
    min1 = minute - (minute % 10)
    min2 = minute % 10
    audio.append(f"{BASE}/{min1}.wav")
    if min2 != 0:
        audio.append(f"{BASE}/{min2}.wav")
else:
    if minute != 0:
        audio.append(f"{BASE}/{minute}.wav")

## add AM or PM to the time stamp
if ampm:
    audio.append(f"{BASE}/{ampm}.wav")

## Speak the time in series to avoid pauses between files
run_audio_command(["aplay"] + audio)
