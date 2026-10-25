#!/usr/bin/env python3
#
## Calomel.org Half-Life 1 (1998 series) talking clock
## Python port of half-life_clock.pl
#

import argparse
from pathlib import Path
import subprocess
from datetime import datetime

## the clips live beside the script, wherever it is deployed
BASE = Path(__file__).resolve().parent / "wavs"
DEFAULT_VOLUME = 50   # matches hlclock.sh
## a full announcement takes a few seconds; a hung aplay (the ALSA meter
## plugin deadlocked on 2026-10-14) held the only playback device for days
DEFAULT_TIMEOUT = 60


def run_audio_command(command, timeout):
    """Stop with a useful diagnostic if an ALSA command fails or hangs."""
    try:
        ## on timeout, subprocess sends SIGKILL: a deadlocked aplay ignores
        ## SIGTERM, since its handler deadlocks closing the device
        subprocess.run(command, check=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        raise SystemExit(
            f"{command[0]} timed out after {timeout} seconds and was killed"
        ) from None
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
parser.add_argument(
    "--timeout", type=int, default=DEFAULT_TIMEOUT,
    help=f"seconds before a hung amixer or aplay is killed "
         f"(default: {DEFAULT_TIMEOUT})"
)
args = parser.parse_args()
if not 0 <= args.volume <= 100:
    parser.error("--volume must be between 0 and 100 (inclusive)")
if args.timeout < 1:
    parser.error("--timeout must be at least 1")

## set PCM volume (was amixer -q -M sset PCM NN% in hlclock*.sh)
run_audio_command(["amixer", "-q", "-M", "sset", "PCM", f"{args.volume}%"],
                  args.timeout)

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
run_audio_command(["aplay"] + audio, args.timeout)
